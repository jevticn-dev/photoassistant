/**
 * The parts of the render that are constant over an image, computed on the CPU.
 *
 * Two kinds of thing live here: the values the shader receives as uniforms
 * (`RENDERER_SPEC.md` §3.1 and §3.2), and the skip rule that decides which
 * operations run at all (§4.1).
 *
 * Why on the CPU. Both are per-image constants, so computing them per pixel
 * would be waste — but the better reason is reach: a plain unit test can assert
 * the white-balance multipliers and the skip flags without a GPU, and those are
 * exactly the two places where a mistake is silent. A wrong multiplier looks like
 * a slightly different photograph; a skip flag left on turns the bit-exact
 * identity test into an approximate one.
 *
 * Arithmetic is rounded to `float32` at each step (`Math.fround`). JavaScript has
 * only doubles, while NumPy computes these in `float32`, and rounding as we go
 * makes the two agree exactly rather than to within a rounding error nobody
 * tracked. It costs a handful of calls once per image.
 */

import { isNeutralCurve, type EditRecipe } from './schema';
import { LUMA_WEIGHTS } from './shader';

/**
 * Strength of the white balance, spec §8.3.
 *
 * Calibrated by the phase 1b probe and raised from 0.5 to 1.5 (ADR-19): at 0.5
 * the ends of the range could only reach a red-to-blue ratio of 2, too little for
 * a tungsten-to-daylight shift, and the fit compensated by draining saturation
 * instead of correcting the cast.
 */
export const K_WB = 1.5;

const f32 = Math.fround;

/**
 * Per-channel multipliers for the linear stage (spec §3.1).
 *
 * Normalising by the multipliers' own luminance is what makes this a purely
 * chromatic operation: neutral grey keeps its brightness, and changing the
 * overall level stays exposure's job.
 */
export function whiteBalanceMultipliers(
  temperature: number,
  tint: number,
): [number, number, number] {
  const t = f32(f32(temperature) / 100);
  const u = f32(f32(tint) / 100);

  const multipliers: [number, number, number] = [
    f32(Math.pow(2, f32(K_WB * t))),
    f32(Math.pow(2, f32(-K_WB * u))),
    f32(Math.pow(2, f32(-K_WB * t))),
  ];

  let luminance = 0;
  for (let i = 0; i < 3; i++) {
    luminance = f32(luminance + f32(multipliers[i] * f32(LUMA_WEIGHTS[i])));
  }

  return [
    f32(multipliers[0] / luminance),
    f32(multipliers[1] / luminance),
    f32(multipliers[2] / luminance),
  ];
}

/** One stop is twice the light (spec §3.2). */
export function exposureScale(stops: number): number {
  return f32(Math.pow(2, f32(stops)));
}

/**
 * Which operations run for a given recipe (spec §4.1).
 *
 * `linearStage` covers steps 1 and 4 together. That pairing is the easiest thing
 * in the whole specification to overlook and it carries the identity test:
 * decoding to linear and encoding back is not an exact inverse in finite
 * precision, so running the pair without cause leaves a neutral recipe returning
 * something a few last bits away from its input.
 */
export interface RenderPlan {
  readonly linearStage: boolean;
  readonly whiteBalance: boolean;
  readonly exposure: boolean;
  readonly regions: boolean;
  readonly contrast: boolean;
  readonly curve: boolean;
  readonly colour: boolean;
}

export function planFor(recipe: EditRecipe): RenderPlan {
  const { whiteBalance, tone, color } = recipe;

  const wantsWhiteBalance = whiteBalance.temperature !== 0 || whiteBalance.tint !== 0;
  const wantsExposure = tone.exposure !== 0;

  return {
    linearStage: wantsWhiteBalance || wantsExposure,
    whiteBalance: wantsWhiteBalance,
    exposure: wantsExposure,
    regions: tone.highlights !== 0 || tone.shadows !== 0 || tone.whites !== 0 || tone.blacks !== 0,
    contrast: tone.contrast !== 0,
    curve: !isNeutralCurve(recipe.toneCurve.points),
    colour: color.saturation !== 0 || color.vibrance !== 0,
  };
}

/** True when the recipe asks the shader to do nothing at all. */
export function isPlanEmpty(plan: RenderPlan): boolean {
  return !(plan.linearStage || plan.regions || plan.contrast || plan.curve || plan.colour);
}

/**
 * Number of entries in the tone-region table, spec §3.3. The same size as the
 * master curve's LUT, and for the same reason: one texture layout, one lookup.
 */
export const REGION_TABLE_SIZE = 1024;

/** Strength of the tone-region shift, spec §8.3. */
export const K_REG = 0.25;

const BLACKS_END = 0.25;
const SHADOWS_END = 0.6;
const HIGHLIGHTS_START = 0.4;
const WHITES_START = 0.75;

/**
 * Spec §7.1. Clamps at both ends, which is what leaves a pixel above white to
 * `whites` alone (§7.3.1).
 */
function smoothstep(edge0: number, edge1: number, x: number): number {
  const raw = f32(f32(x - edge0) / f32(edge1 - edge0));
  const t = f32(Math.min(Math.max(raw, 0), 1));
  return f32(f32(t * t) * f32(3 - f32(2 * t)));
}

function maskBlacks(y: number): number {
  return f32(1 - smoothstep(0, BLACKS_END, y));
}

function maskShadows(y: number): number {
  return f32(smoothstep(0, BLACKS_END, y) * f32(1 - smoothstep(BLACKS_END, SHADOWS_END, y)));
}

function maskHighlights(y: number): number {
  return f32(
    smoothstep(HIGHLIGHTS_START, WHITES_START, y) * f32(1 - smoothstep(WHITES_START, 1, y)),
  );
}

function maskWhites(y: number): number {
  return smoothstep(WHITES_START, 1, y);
}

/**
 * The shift every luma level receives, made monotone (spec §3.3, ADR-22).
 *
 * Built once per recipe on the CPU, exactly as the master curve's table is, and
 * uploaded as a texture. The shader does a lookup and nothing else.
 *
 * **Why it has to be monotone.** Each mask has an edge 0.25 wide and the total
 * shift is their sum, so their slopes add. Past a certain strength the shift
 * falls faster than brightness rises, two neighbouring pixels come out in the
 * opposite order, and a smooth sky shows a band. Nine of 1012 fitted recipes did
 * it, the worst reversing by 34 steps of 255.
 *
 * **Why a running maximum.** The table is already dense, so the condition reduces
 * to a comparison and an assignment — no arithmetic, and therefore no last-bit
 * disagreement with the NumPy side.
 *
 * **Why it stores the shift and not the resulting luma.** Lookups clip their
 * input (§6.4). A table of results would give every luma above 1 the result at 1
 * and flatten the highlight headroom §5 exists to keep. A shift is correct
 * outside the range too, because the masks saturate there.
 */
export function buildRegionTable(recipe: EditRecipe): Float32Array {
  const tone = recipe.tone;
  const highlights = f32(tone.highlights / 100);
  const shadows = f32(tone.shadows / 100);
  const whites = f32(tone.whites / 100);
  const blacks = f32(tone.blacks / 100);

  const table = new Float32Array(REGION_TABLE_SIZE);

  let running = -Infinity;
  for (let index = 0; index < REGION_TABLE_SIZE; index += 1) {
    const y = f32(index / (REGION_TABLE_SIZE - 1));

    // Left to right, because NumPy's `a + b + c + d` is ((a + b) + c) + d and a
    // different association can differ in the last bit of a float32.
    let sum = f32(highlights * maskHighlights(y));
    sum = f32(sum + f32(shadows * maskShadows(y)));
    sum = f32(sum + f32(whites * maskWhites(y)));
    sum = f32(sum + f32(blacks * maskBlacks(y)));
    const out = f32(y + f32(K_REG * sum));

    running = out > running ? out : running;
    table[index] = f32(running - y);
  }

  return table;
}
