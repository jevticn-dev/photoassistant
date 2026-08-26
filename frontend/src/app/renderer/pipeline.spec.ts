/**
 * The two things computed on the CPU: the white-balance multipliers and the skip
 * rule.
 *
 * The multiplier assertions are the same ones as
 * `ml/tests/test_renderer_operations.py`, because they assert the same *Namera*
 * sentence from `RENDERER_SPEC.md` §3.1 — and §3 says the intent is
 * authoritative, so both implementations have to be held to it, not to each
 * other's formula.
 *
 * The skip rule (§4.1) is asserted here rather than through a rendered image
 * because that is where it can be seen directly. Its effect on the image is the
 * bit-exact identity test in `renderer.browser.spec.ts`.
 */

import { describe, expect, it } from 'vitest';

import { K_WB, exposureScale, isPlanEmpty, planFor, whiteBalanceMultipliers } from './pipeline';
import { LUMA_WEIGHTS } from './shader';
import { NEUTRAL_RECIPE, parseRecipe, type EditRecipe } from './schema';

function recipe(values: Partial<Record<string, number>>): EditRecipe {
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
    groups[where[key]][key] = value as number;
  }

  return parseRecipe({ schema: 1, ...groups });
}

describe('white balance (spec §3.1)', () => {
  it('does not change brightness', () => {
    // Namera: shift the colour balance, leave overall brightness to exposure.
    for (const [temperature, tint] of [
      [100, 0],
      [-100, 0],
      [0, 100],
      [60, -40],
    ]) {
      const multipliers = whiteBalanceMultipliers(temperature, tint);
      const luminance =
        multipliers[0] * LUMA_WEIGHTS[0] +
        multipliers[1] * LUMA_WEIGHTS[1] +
        multipliers[2] * LUMA_WEIGHTS[2];

      expect(luminance).toBeCloseTo(1, 6);
    }
  });

  it('warms towards red and away from blue', () => {
    const warm = whiteBalanceMultipliers(100, 0);
    const cool = whiteBalanceMultipliers(-100, 0);

    expect(warm[0], 'positive temperature must favour red over blue').toBeGreaterThan(warm[2]);
    expect(cool[0]).toBeLessThan(cool[2]);

    // At the range limit the red-to-blue ratio is 2^(2 * K_WB) = 8. It was 2
    // until the phase 1b probe showed that too narrow to express a
    // tungsten-to-daylight correction, and the fit drained saturation instead
    // (ADR-19).
    expect(K_WB).toBe(1.5);
    expect(warm[0] / warm[2]).toBeCloseTo(8, 4);
  });

  it('moves tint along the green-magenta axis', () => {
    const magenta = whiteBalanceMultipliers(0, 100);

    expect(magenta[1], 'positive tint must cut green').toBeLessThan(magenta[0]);
    expect(magenta[0]).toBeCloseTo(magenta[2], 6);
  });

  it('is the identity when neutral', () => {
    expect(whiteBalanceMultipliers(0, 0)).toEqual([1, 1, 1]);
  });
});

describe('exposure (spec §3.2)', () => {
  it('makes one stop twice the light', () => {
    expect(exposureScale(0)).toBe(1);
    expect(exposureScale(1)).toBe(2);
    expect(exposureScale(-1)).toBe(0.5);
    expect(exposureScale(2)).toBe(4);
  });
});

describe('the skip rule (spec §4.1)', () => {
  it('skips everything for a neutral recipe', () => {
    const plan = planFor(NEUTRAL_RECIPE);

    expect(plan).toEqual({
      linearStage: false,
      whiteBalance: false,
      exposure: false,
      regions: false,
      contrast: false,
      curve: false,
      colour: false,
    });
    expect(isPlanEmpty(plan)).toBe(true);
  });

  it('runs the linear stage for exposure alone', () => {
    // Steps 1 and 4 exist only to serve steps 2 and 3, so they live and die with
    // them — the line the bit-exact identity test depends on.
    const plan = planFor(recipe({ exposure: 1 }));

    expect(plan.linearStage).toBe(true);
    expect(plan.exposure).toBe(true);
    expect(plan.whiteBalance).toBe(false);
  });

  it('runs the linear stage for tint alone', () => {
    const plan = planFor(recipe({ tint: -6 }));

    expect(plan.linearStage).toBe(true);
    expect(plan.whiteBalance).toBe(true);
  });

  it('leaves the linear stage off for a gamma-space parameter', () => {
    // Contrast lives in gamma space; decoding and encoding around it would be a
    // round trip that is not an exact inverse, for nothing.
    const plan = planFor(recipe({ contrast: 40 }));

    expect(plan.linearStage).toBe(false);
    expect(plan.contrast).toBe(true);
  });

  it.each(['highlights', 'shadows', 'whites', 'blacks'])(
    'runs the tone regions for %s alone',
    (parameter) => {
      expect(planFor(recipe({ [parameter]: 20 })).regions).toBe(true);
    },
  );

  it('skips the curve only for the diagonal', () => {
    expect(planFor(NEUTRAL_RECIPE).curve).toBe(false);
    expect(
      planFor(
        parseRecipe({
          schema: 1,
          tone_curve: {
            points: [
              [0, 0.1],
              [1, 1],
            ],
          },
        }),
      ).curve,
    ).toBe(true);
  });

  it.each(['saturation', 'vibrance'])('runs the colour stage for %s alone', (parameter) => {
    expect(planFor(recipe({ [parameter]: 25 })).colour).toBe(true);
  });
});
