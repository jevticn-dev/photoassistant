/**
 * The WebGL2 renderer, asserted through the GPU it actually runs on.
 *
 * `RENDERER_SPEC.md` §3 opens every parameter with a one-sentence statement of
 * intent — *Namera* — and the rule there is that **the intent is authoritative**:
 * if formula and intent disagree, the formula is wrong.
 * `ml/tests/test_renderer_operations.py` asserts those sentences against the
 * NumPy implementation; this file asserts the same sentences against the shader.
 * Two implementations checked against each other's output would agree on a
 * shared misreading; checked against the same intent, they cannot.
 *
 * Everything here runs in a real browser (`npm run test:browser`) because there
 * is no honest way to test a fragment shader without one. `headless-gl` was
 * rejected outright: it implements WebGL 1.0, so it cannot compile GLSL ES 3.00
 * and would be testing a program that does not exist.
 *
 * The output is 8-bit, which sets the resolution of every assertion here: one
 * step is 1/255 ≈ 0.0039. That is not a limitation to work around — it is the
 * space the golden test compares in (§8.4). Tolerances below are written as
 * multiples of that step, and `closeTo` takes an absolute tolerance rather than
 * Vitest's `toBeCloseTo`, whose second argument counts decimal digits and would
 * quietly turn "within one 8-bit step" into "within half a unit".
 */

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { applyLut, buildLut } from './curve';
import { WebGlRenderer, type PixelSource } from './renderer';
import { NEUTRAL_RECIPE, parseRecipe, type CurvePoint, type EditRecipe } from './schema';

const LUMA_WEIGHTS = [0.2126, 0.7152, 0.0722] as const;

/** One 8-bit step, the unit every tolerance in this file is expressed in. */
const STEP = 1 / 255;

let renderer: WebGlRenderer;

beforeAll(() => {
  renderer = WebGlRenderer.create(document.createElement('canvas'));
});

afterAll(() => {
  renderer.dispose();
});

// ------------------------------------------------------------------ helpers

function closeTo(actual: number, expected: number, tolerance: number, because = ''): void {
  const gap = Math.abs(actual - expected);
  expect(
    gap,
    `${because}: ${actual} is ${gap.toExponential(2)} from ${expected}, allowed ${tolerance}`,
  ).toBeLessThanOrEqual(tolerance);
}

function recipe(values: Record<string, number>): EditRecipe {
  const where: Record<string, string> = {
    temperature: 'white_balance',
    tint: 'white_balance',
    exposure: 'tone',
    contrast: 'tone',
    highlights: 'tone',
    shadows: 'tone',
    whites: 'tone',
    blacks: 'tone',
    saturation: 'color',
    vibrance: 'color',
  };

  const groups: Record<string, Record<string, number>> = {
    white_balance: {},
    tone: {},
    color: {},
  };
  for (const [key, value] of Object.entries(values)) {
    groups[where[key]][key] = value;
  }

  return parseRecipe({ schema: 1, ...groups });
}

function curveRecipe(points: CurvePoint[]): EditRecipe {
  return parseRecipe({ schema: 1, tone_curve: { points } });
}

/** An image one pixel high, from float RGB triples, quantised the shared way (§8.4). */
function imageOf(pixels: readonly (readonly [number, number, number])[]): PixelSource {
  const data = new Uint8Array(pixels.length * 4);
  pixels.forEach(([r, g, b], index) => {
    data[index * 4 + 0] = Math.floor(Math.min(Math.max(r, 0), 1) * 255 + 0.5);
    data[index * 4 + 1] = Math.floor(Math.min(Math.max(g, 0), 1) * 255 + 0.5);
    data[index * 4 + 2] = Math.floor(Math.min(Math.max(b, 0), 1) * 255 + 0.5);
    data[index * 4 + 3] = 255;
  });
  return { data, width: pixels.length, height: 1 };
}

/** Every 8-bit grey level, one pixel each — the densest input the curve will see. */
function greyWedge(): PixelSource {
  const pixels: [number, number, number][] = [];
  for (let value = 0; value < 256; value++) {
    pixels.push([value / 255, value / 255, value / 255]);
  }
  return imageOf(pixels);
}

/** Render and return the result as float RGB triples in [0, 1]. */
function render(image: PixelSource, edit: EditRecipe): [number, number, number][] {
  renderer.setImage(image);
  const { data } = renderer.readPixels(edit);

  const out: [number, number, number][] = [];
  for (let i = 0; i < image.width * image.height; i++) {
    out.push([data[i * 4] / 255, data[i * 4 + 1] / 255, data[i * 4 + 2] / 255]);
  }
  return out;
}

function srgbDecode(s: number): number {
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

/**
 * Rec.709 **luminance** — the weights over linear light, not over the gamma
 * values that §2.2's luma uses. White balance is defined to preserve this one:
 * it divides its multipliers by their own luminance (§3.1), which is a statement
 * about linear light. The gamma-space luma of a grey pixel does move, and
 * asserting on it would be asserting the wrong invariant.
 */
function linearLuminance([r, g, b]: readonly [number, number, number]): number {
  return (
    LUMA_WEIGHTS[0] * srgbDecode(r) +
    LUMA_WEIGHTS[1] * srgbDecode(g) +
    LUMA_WEIGHTS[2] * srgbDecode(b)
  );
}

function luma([r, g, b]: readonly [number, number, number]): number {
  return LUMA_WEIGHTS[0] * r + LUMA_WEIGHTS[1] * g + LUMA_WEIGHTS[2] * b;
}

// ------------------------------------------------------------------- §4.1

describe('identity (spec §4.1 and §8.5)', () => {
  it('returns a neutral recipe bit for bit', () => {
    // Bit-exact, not approximately equal. It holds because a neutral recipe
    // performs no arithmetic at all: every operation is skipped, and steps 1 and
    // 4 are skipped together with white balance and exposure. A failure here
    // means the skip logic, not precision.
    //
    // The image is deliberately asymmetric top to bottom, so this also pins the
    // row order: the texture goes up with row 0 first and readPixels reads
    // bottom-up, and a missing flip on read-back would show here rather than as
    // an upside-down preview nobody scripted.
    const data = new Uint8Array(4 * 4 * 4);
    for (let row = 0; row < 4; row++) {
      for (let column = 0; column < 4; column++) {
        const at = (row * 4 + column) * 4;
        data[at + 0] = row * 60 + 3;
        data[at + 1] = column * 37 + 11;
        data[at + 2] = row * 17 + column * 5;
        data[at + 3] = 255;
      }
    }
    const image: PixelSource = { data, width: 4, height: 4 };

    renderer.setImage(image);
    const out = renderer.readPixels(NEUTRAL_RECIPE);

    expect([...out.data]).toEqual([...data]);
  });

  it('changes something for every non-neutral recipe', () => {
    // Guards the test above: a renderer that did nothing would pass it.
    //
    // The image has to earn each row of the list. A grey wedge alone would not:
    // saturation scales the distance from grey, so on neutral pixels it is
    // correctly a no-op and the guard would fail on a working renderer. The dark
    // step is here for the same reason — a negative blacks on pure black clips
    // back to black and moves nothing.
    const image = imageOf([
      [0, 0, 0],
      [0.1, 0.1, 0.1],
      [0.5, 0.5, 0.5],
      [1, 1, 1],
      [0.8, 0.2, 0.4],
      [0.2, 0.6, 0.9],
    ]);
    const edits: EditRecipe[] = [
      recipe({ contrast: 40 }),
      recipe({ exposure: 0.5 }),
      recipe({ blacks: -40 }),
      recipe({ saturation: 50 }),
      curveRecipe([
        [0, 0.08],
        [1, 0.95],
      ]),
    ];

    for (const edit of edits) {
      renderer.setImage(image);
      expect([...renderer.readPixels(edit).data]).not.toEqual([...image.data]);
    }
  });
});

// ------------------------------------------------------------------- §3.1

describe('white balance (spec §3.1)', () => {
  it('does not change the brightness of neutral grey', () => {
    // Namera: shift the colour balance, leave overall brightness to exposure.
    const grey = imageOf([[0.5, 0.5, 0.5]]);
    const before = linearLuminance(render(grey, NEUTRAL_RECIPE)[0]);

    for (const [label, edit] of [
      ['warm', recipe({ temperature: 100 })],
      ['cool', recipe({ temperature: -100 })],
      ['magenta', recipe({ tint: 100 })],
      ['both', recipe({ temperature: 60, tint: -40 })],
    ] as const) {
      // At the ends of the range the three channels land far apart, and the
      // coarsest of them carries about two 8-bit steps of rounding into linear
      // light. Measured worst case over these four: 0.0023.
      closeTo(linearLuminance(render(grey, edit)[0]), before, 0.005, label);
    }
  });

  it('warms towards red and away from blue', () => {
    const grey = imageOf([[0.5, 0.5, 0.5]]);

    const [warm] = render(grey, recipe({ temperature: 100 }));
    const [cool] = render(grey, recipe({ temperature: -100 }));

    expect(warm[0], 'positive temperature must favour red over blue').toBeGreaterThan(warm[2]);
    expect(cool[0]).toBeLessThan(cool[2]);
  });

  it('moves tint along the green-magenta axis', () => {
    const grey = imageOf([[0.5, 0.5, 0.5]]);

    const [magenta] = render(grey, recipe({ tint: 100 }));

    expect(magenta[1], 'positive tint must cut green').toBeLessThan(magenta[0]);
    closeTo(magenta[0], magenta[2], STEP, 'red and blue move together');
  });
});

// ------------------------------------------------------------------- §3.2

describe('exposure (spec §3.2)', () => {
  it('makes one stop twice the light', () => {
    // Namera: +1 means double the light, as one stop on a camera does.
    const before = imageOf([[0.2, 0.2, 0.2]]);

    const [after] = render(before, recipe({ exposure: 1 }));

    closeTo(srgbDecode(after[0]), 2 * srgbDecode(0.2), 0.001, 'one stop');
  });

  it('leaves the colour ratios alone', () => {
    const source = imageOf([[0.3, 0.15, 0.08]]);
    const [before] = render(source, NEUTRAL_RECIPE);
    const [after] = render(source, recipe({ exposure: 0.5 }));

    const ratio = (pixel: readonly [number, number, number]) =>
      srgbDecode(pixel[1]) / srgbDecode(pixel[0]);

    closeTo(ratio(after), ratio(before), 0.01, 'green to red ratio');
  });
});

// ------------------------------------------------------------------- §3.3

describe('tone regions (spec §3.3)', () => {
  it('lifts the dark end with blacks and leaves the rest', () => {
    // Namera: brighten or darken only part of the range, midtones untouched.
    const wedge = greyWedge();
    const before = render(wedge, NEUTRAL_RECIPE);
    const after = render(wedge, recipe({ blacks: 100 }));

    const shift = (index: number) => after[index][0] - before[index][0];

    closeTo(shift(0), 0.25, STEP, 'full lift at black');
    closeTo(shift(255), 0, STEP, 'nothing at white');
    closeTo(shift(128), 0, STEP, 'nothing at mid grey');
  });

  it('recovers only the bright end with highlights', () => {
    const wedge = greyWedge();
    const before = render(wedge, NEUTRAL_RECIPE);
    const after = render(wedge, recipe({ highlights: -100 }));

    for (let i = 0; i < 100; i++) {
      closeTo(after[i][0] - before[i][0], 0, STEP, `below the window at ${i}`);
    }
    expect(after[200][0] - before[200][0], 'the bright end must come down').toBeLessThan(-0.1);
  });

  it('shifts every channel by the same amount', () => {
    // A shared shift changes brightness without dragging the hue with it.
    const coloured = imageOf([[0.1, 0.3, 0.55]]);
    const [before] = render(coloured, NEUTRAL_RECIPE);
    const [after] = render(coloured, recipe({ shadows: 60 }));

    const deltas = [after[0] - before[0], after[1] - before[1], after[2] - before[2]];
    // Each channel rounds on its own, so a shared shift can still come out one
    // 8-bit step apart. Anything beyond that is a hue shift.
    closeTo(Math.max(...deltas) - Math.min(...deltas), 0, 1.5 * STEP, 'channel spread');
  });
});

// ----------------------------------------------------------------- §7.3.1

describe('above white (spec §7.3.1)', () => {
  it('keeps the headroom until step 11', () => {
    // Exposure can take a value above 1 in linear space. If step 4 clipped, the
    // headroom would be gone and no later operation could bring it back.
    const image = imageOf([[0.6, 0.6, 0.6]]);

    const [lifted] = render(image, recipe({ exposure: 2 }));
    const [recovered] = render(image, recipe({ exposure: 2, whites: -100 }));

    closeTo(lifted[0], 1, STEP, 'exposure alone clips to white');
    expect(recovered[0], 'the value above white was still there to pull back').toBeLessThan(0.95);
  });

  it('gives a blown pixel to whites alone, not to highlights', () => {
    // smoothstep clamps, so above luma 1 the highlights window has already
    // closed and whites is fully open. Defensible — whites owns the extreme end
    // by design — but the opposite of the habit most editors teach, where
    // Highlights is the recovery slider. Pinned in both implementations so the
    // golden test never has to report it as an unexplained difference.
    const image = imageOf([[0.6, 0.6, 0.6]]);

    const [withHighlights] = render(image, recipe({ exposure: 2, highlights: -100 }));
    const [withWhites] = render(image, recipe({ exposure: 2, whites: -100 }));

    closeTo(withHighlights[0], 1, STEP, 'highlights cannot reach a blown pixel');
    expect(withWhites[0], 'whites can').toBeLessThan(0.95);
  });
});

// ------------------------------------------------------------------- §3.4

describe('contrast (spec §3.4)', () => {
  it('leaves mid grey where it is', () => {
    // Namera: pull the ends apart around mid grey, which itself does not move.
    const grey = imageOf([[0.5, 0.5, 0.5]]);
    const before = render(grey, NEUTRAL_RECIPE)[0][0];

    for (const amount of [-100, -40, 40, 100]) {
      closeTo(render(grey, recipe({ contrast: amount }))[0][0], before, STEP, `at ${amount}`);
    }
  });

  it('darkens darks and brightens brights when positive', () => {
    const image = imageOf([
      [0.25, 0.25, 0.25],
      [0.75, 0.75, 0.75],
    ]);
    const before = render(image, NEUTRAL_RECIPE);

    const after = render(image, recipe({ contrast: 50 }));

    expect(after[0][0]).toBeLessThan(before[0][0]);
    expect(after[1][0]).toBeGreaterThan(before[1][0]);
  });

  it('does the opposite when negative', () => {
    const image = imageOf([
      [0.25, 0.25, 0.25],
      [0.75, 0.75, 0.75],
    ]);
    const before = render(image, NEUTRAL_RECIPE);

    const after = render(image, recipe({ contrast: -50 }));

    expect(after[0][0]).toBeGreaterThan(before[0][0]);
    expect(after[1][0]).toBeLessThan(before[1][0]);
  });

  it.each([-100, -50, 50, 100])('stays monotone and in range at %s', (amount) => {
    // Non-monotone contrast would invert a gradient; out of range would clip
    // early.
    const out = render(greyWedge(), recipe({ contrast: amount }));

    for (let i = 1; i < out.length; i++) {
      expect(out[i][0]).toBeGreaterThanOrEqual(out[i - 1][0]);
    }
    expect(Math.min(...out.map((pixel) => pixel[0]))).toBeGreaterThanOrEqual(0);
    expect(Math.max(...out.map((pixel) => pixel[0]))).toBeLessThanOrEqual(1);
  });
});

// --------------------------------------------------------------- §3.5, §6

describe('the tone curve (spec §3.5 and §6)', () => {
  const POINTS: CurvePoint[] = [
    [0, 0.08],
    [0.25, 0.28],
    [0.75, 0.8],
    [1, 0.95],
  ];

  it('applies the same table to all three channels', () => {
    // Namera: an arbitrary mapping of brightness, applied alike to every
    // channel, so grey stays grey and the colour balance does not move.
    const image = imageOf([
      [0.1, 0.1, 0.1],
      [0.5, 0.5, 0.5],
      [0.9, 0.9, 0.9],
    ]);

    for (const [r, g, b] of render(image, curveRecipe(POINTS))) {
      expect(r).toBe(g);
      expect(g).toBe(b);
    }
  });

  it('matches the table computed on the CPU', () => {
    // This is the assertion standing behind §6.5. The shader reads the LUT with
    // NEAREST sampling, two texelFetch calls and its own lerp; had it read the
    // table through GL_LINEAR, the interpolation weight would be computed at an
    // implementation-defined precision, and a comparison against the same
    // arithmetic on the CPU is where that would surface.
    const lut = buildLut(POINTS);

    const out = render(greyWedge(), curveRecipe(POINTS));

    let worst = 0;
    for (let value = 0; value < 256; value++) {
      const expected = Math.floor(Math.min(Math.max(applyLut(lut, value / 255), 0), 1) * 255 + 0.5);
      worst = Math.max(worst, Math.abs(Math.round(out[value][0] * 255) - expected));
    }

    // One 8-bit unit is the whole allowance: OpenGL does not prescribe the
    // rounding of an exact half, so a value landing on the boundary may differ
    // by one. Anything larger is an arithmetic difference, not rounding.
    expect(worst, 'largest disagreement with the CPU table, in 8-bit units').toBeLessThanOrEqual(1);
  });

  it('hits the ends of the curve', () => {
    const out = render(
      imageOf([
        [0, 0, 0],
        [1, 1, 1],
      ]),
      curveRecipe(POINTS),
    );

    closeTo(out[0][0], 0.08, STEP, 'black point');
    closeTo(out[1][0], 0.95, STEP, 'white point');
  });
});

// ------------------------------------------------------------------- §3.6

describe('saturation and vibrance (spec §3.6)', () => {
  it('removes all colour at saturation -100', () => {
    // Namera: saturation acts on every colour equally; -100 leaves grey.
    const coloured: [number, number, number] = [0.8, 0.2, 0.4];

    const [out] = render(imageOf([coloured]), recipe({ saturation: -100 }));

    closeTo(Math.max(...out) - Math.min(...out), 0, STEP, 'no colour left');
    closeTo(out[0], luma(coloured), 1.5 * STEP, 'what is left is the luma');
  });

  it('leaves a grey pixel alone', () => {
    const grey = imageOf([[0.5, 0.5, 0.5]]);
    const before = render(grey, NEUTRAL_RECIPE)[0][0];

    for (const amount of [-100, -30, 30, 100]) {
      const [out] = render(grey, recipe({ saturation: amount }));
      for (const channel of out) {
        closeTo(channel, before, STEP, `grey at saturation ${amount}`);
      }
    }
  });

  it('spares with vibrance what is already saturated', () => {
    // Namera: vibrance acts harder on pale colour than on vivid colour. This is
    // the only behavioural difference between vibrance and saturation, and it is
    // why the fixture set needs a saturation ramp.
    const pale: [number, number, number] = [0.6, 0.5, 0.45];
    const vivid: [number, number, number] = [0.95, 0.05, 0.05];

    const gain = (pixel: [number, number, number]) => {
      const [before] = render(imageOf([pixel]), NEUTRAL_RECIPE);
      const [after] = render(imageOf([pixel]), recipe({ vibrance: 80 }));
      const spreadBefore = Math.max(...before) - Math.min(...before);
      const spreadAfter = Math.max(...after) - Math.min(...after);
      return spreadAfter / spreadBefore - 1;
    };

    // Compared as a gain, not as an absolute shift: the vivid pixel starts much
    // further from grey, so measuring absolute movement would partly hide the
    // very selectivity being tested.
    expect(gain(pale), 'vibrance must favour the less saturated pixel').toBeGreaterThan(
      gain(vivid) * 5,
    );
  });

  it('treats both alike with plain saturation', () => {
    // The contrast to the test above.
    //
    // The vivid pixel here is weaker than the one above, and deliberately so:
    // step 11 clips, and pushing [0.95, 0.05, 0.05] through +50 saturation sends
    // both ends past the range. Its spread would then be the width of the range
    // rather than the gain, and the test would report a difference that comes
    // from clipping, not from the operation. This one has room to move.
    const pale: [number, number, number] = [0.6, 0.5, 0.45];
    const strong: [number, number, number] = [0.75, 0.25, 0.25];

    const relativeChange = (pixel: [number, number, number]) => {
      const [before] = render(imageOf([pixel]), NEUTRAL_RECIPE);
      const [after] = render(imageOf([pixel]), recipe({ saturation: 30 }));
      return (
        (Math.max(...after) - Math.min(...after)) / (Math.max(...before) - Math.min(...before))
      );
    };

    // The pale pixel spans 38 8-bit steps, so a unit of rounding is worth about
    // 3% of its spread; the strong one spans 128 and is near exact. The vibrance
    // test above separates its two pixels by a factor of five, well outside this.
    closeTo(relativeChange(pale), relativeChange(strong), 0.05, 'saturation is indiscriminate');
  });
});

// ------------------------------------------------------------ §9, plan §11

describe('the implementation layer', () => {
  it('reports a texture limit and refuses an image above it', () => {
    // MAX_TEXTURE_SIZE is a device property, not a constant (plan §11). WebGL2
    // guarantees at least 2048, which is exactly the proxy size the editor
    // intends to use — so the check has to be a check, not an assumption.
    const limit = renderer.maxImageSize;
    expect(limit).toBeGreaterThanOrEqual(2048);

    expect(() =>
      renderer.setImage({ data: new Uint8Array(4), width: limit + 1, height: 1 }),
    ).toThrow(/caps textures at/);
  });
});
