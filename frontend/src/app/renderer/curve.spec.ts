/**
 * The tone curve, its interpolation and its LUT (spec §6).
 *
 * Most of these assertions are about the *table*, not about any image. That is
 * the point of the design: the delicate work happens 1024 times in total, so
 * agreement between the two implementations reduces to comparing two arrays of
 * 1024 numbers — a question with a yes-or-no answer and no picture involved.
 *
 * Deliberately the same assertions as `ml/tests/test_renderer_curve.py`, over the
 * same control points. Two implementations tested against different properties
 * would agree on the tests and still disagree on the curve.
 */

import { describe, expect, it } from 'vitest';

import { LUT_SIZE, applyLut, buildLut, evaluate, tangents, type CurvePoints } from './curve';
import { isNeutralCurve } from './schema';

const DIAGONAL: CurvePoints = [
  [0, 0],
  [1, 1],
];

/** FiveK "Medium Contrast", 12.4% of the catalogue's edits (edit_schema §4). */
const MEDIUM_CONTRAST: CurvePoints = [
  [0, 0],
  [32 / 255, 22 / 255],
  [64 / 255, 56 / 255],
  [128 / 255, 128 / 255],
  [192 / 255, 196 / 255],
  [1, 1],
];

/**
 * Deliberately harsh: a steep middle segment beside shallow ones, which is what
 * makes an uncorrected cubic overshoot.
 */
const AGGRESSIVE: CurvePoints = [
  [0, 0],
  [0.18, 0.02],
  [0.35, 0.62],
  [0.62, 0.66],
  [1, 1],
];

const CASES: [string, CurvePoints][] = [
  ['diagonal', DIAGONAL],
  ['FiveK medium contrast', MEDIUM_CONTRAST],
  ['aggressive points', AGGRESSIVE],
];

function isMonotone(values: ArrayLike<number>, tolerance = 1e-9): boolean {
  for (let i = 1; i < values.length; i++) {
    if (values[i] - values[i - 1] < -tolerance) {
      return false;
    }
  }
  return true;
}

describe('monotone cubic interpolation', () => {
  it.each(CASES)('passes exactly through every control point: %s', (_label, points) => {
    // Interpolation, not approximation: dragging a point must do what it says.
    const slopes = tangents(points);

    for (const [x, y] of points) {
      expect(evaluate(points, slopes, x)).toBeCloseTo(y, 12);
    }
  });

  it.each(CASES)('builds a monotone table: %s', (_label, points) => {
    // A dip would invert a gradient — a visible band, not a rounding matter.
    expect(isMonotone(buildLut(points))).toBe(true);
  });

  it('actually fires the correction on the aggressive points', () => {
    // Guards the test above: monotonicity that never needed enforcing proves
    // little. Without a case where the raw three-point tangents overshoot, the
    // Fritsch-Carlson step could be missing entirely and every test still pass.
    const secants: number[] = [];
    for (let i = 0; i < AGGRESSIVE.length - 1; i++) {
      secants.push(
        (AGGRESSIVE[i + 1][1] - AGGRESSIVE[i][1]) / (AGGRESSIVE[i + 1][0] - AGGRESSIVE[i][0]),
      );
    }

    const raw = AGGRESSIVE.map((_, i) => {
      if (i === 0) {
        return secants[0];
      }
      if (i === AGGRESSIVE.length - 1) {
        return secants[secants.length - 1];
      }
      return (secants[i - 1] + secants[i]) / 2;
    });

    const corrected = tangents(AGGRESSIVE);

    const untouched = raw.every((value, i) => Math.abs(value - corrected[i]) < 1e-12);
    expect(untouched, 'the correction left the tangents untouched').toBe(false);

    // And after correcting, every segment sits inside the radius-3 circle.
    for (let i = 0; i < secants.length; i++) {
      if (secants[i] === 0) {
        continue;
      }
      const alpha = corrected[i] / secants[i];
      const beta = corrected[i + 1] / secants[i];
      expect(alpha * alpha + beta * beta).toBeLessThanOrEqual(9 + 1e-9);
    }
  });

  it('keeps a flat segment flat', () => {
    const points: CurvePoints = [
      [0, 0],
      [0.3, 0.5],
      [0.7, 0.5],
      [1, 1],
    ];

    const slopes = tangents(points);

    expect(slopes[1]).toBe(0);
    expect(slopes[2]).toBe(0);
    for (let i = 0; i <= 50; i++) {
      expect(evaluate(points, slopes, 0.3 + (0.4 * i) / 50)).toBeCloseTo(0.5, 12);
    }
  });
});

describe('the lookup table', () => {
  it('has the size the spec fixes', () => {
    expect(LUT_SIZE).toBe(1024);
    expect(buildLut(MEDIUM_CONTRAST).length).toBe(1024);
  });

  it('hits the ends of the curve exactly', () => {
    // Sampling at i/(N-1) is what makes lut[0] and lut[N-1] exact, not near.
    const lut = buildLut([
      [0, 0.08],
      [0.5, 0.5],
      [1, 0.95],
    ]);

    expect(lut[0]).toBeCloseTo(0.08, 6);
    expect(lut[lut.length - 1]).toBeCloseTo(0.95, 6);
  });

  it('turns the diagonal into the identity table', () => {
    const lut = buildLut(DIAGONAL);

    for (let i = 0; i < LUT_SIZE; i++) {
      expect(lut[i]).toBeCloseTo(i / (LUT_SIZE - 1), 6);
    }
  });

  it('agrees with the curve it samples', () => {
    // The approximation error of the table, measured rather than assumed. A
    // 1024-entry table spaced over [0, 1] steps by 0.00098, well under the 8-bit
    // output step of 1/255 = 0.0039, so the error disappears in quantisation.
    const slopes = tangents(MEDIUM_CONTRAST);
    const lut = buildLut(MEDIUM_CONTRAST);

    let worst = 0;
    for (let i = 0; i <= 500; i++) {
      const x = i / 500;
      worst = Math.max(worst, Math.abs(evaluate(MEDIUM_CONTRAST, slopes, x) - applyLut(lut, x)));
    }

    expect(worst, `table error ${worst.toExponential(2)} is not negligible at 8 bits`).toBeLessThan(
      1 / 255 / 4,
    );
  });

  it('clamps its input', () => {
    // After the tone regions and contrast a value may leave [0, 1]; the index
    // cannot.
    const lut = buildLut(MEDIUM_CONTRAST);

    expect(applyLut(lut, -0.5)).toBeCloseTo(lut[0], 6);
    expect(applyLut(lut, 1.5)).toBeCloseTo(lut[lut.length - 1], 6);
  });
});

describe('identity recognition', () => {
  it('recognises only the diagonal', () => {
    expect(isNeutralCurve(DIAGONAL)).toBe(true);
    expect(isNeutralCurve(MEDIUM_CONTRAST)).toBe(false);
    expect(
      isNeutralCurve([
        [0, 0.1],
        [1, 1],
      ]),
      'a lifted black point is not the identity',
    ).toBe(false);
  });
});
