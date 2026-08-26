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
