/**
 * The master tone curve: monotone interpolation and its 1024-entry LUT.
 *
 * Implements `RENDERER_SPEC.md` §6, and is the TypeScript half of the pair whose
 * agreement matters most. The Python half is
 * `ml/photoassistant/renderer/curve.py`; neither is derived from the other, both
 * translate the same text.
 *
 * Written out rather than taken from a library, and that is the whole point.
 * TypeScript has no `scipy`, so a library here would mean two different
 * algorithms — and monotone cubic interpolation is exactly where two
 * implementations drift apart quietly: tangent choice, the monotonicity
 * correction, endpoint handling. Writing both by hand from one specification is
 * the only arrangement in which "the algorithm is the same" is a claim rather
 * than a hope. It is also why the Python side does not use `scipy.interpolate`.
 *
 * The table is what makes the claim cheap to check. The awkward work runs 1024
 * times in total, not per pixel, so agreement reduces to comparing two arrays of
 * 1024 numbers with no image involved (§6.6).
 *
 * Precision note. The table is computed in JavaScript numbers — doubles — and
 * stored as `Float32Array`, which is what gets uploaded as a float texture. That
 * matches the Python side, which builds in `float64` and stores `float32`, and it
 * is not a departure from the spec's `float32` contract (§8.1): that contract
 * governs the per-pixel path.
 */

export const LUT_SIZE = 1024;

/**
 * Fritsch-Carlson: tangents stay inside a circle of radius 3 around the secant.
 * Proven sufficient for monotonicity, not a heuristic.
 */
const MONOTONICITY_RADIUS_SQUARED = 9;

export type CurvePoints = readonly (readonly [number, number])[];

/**
 * Slopes at each control point, corrected so the curve cannot overshoot.
 *
 * Three steps, in the order the spec fixes them (§6.2): secant slopes, then a
 * three-point average for the interior tangents, then the Fritsch-Carlson
 * correction applied segment by segment in increasing order. The order is part of
 * the specification — a correction on one segment is visible to the next.
 */
export function tangents(points: CurvePoints): Float64Array {
  const n = points.length;
  const secants = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    secants[i] = (points[i + 1][1] - points[i][1]) / (points[i + 1][0] - points[i][0]);
  }

  const m = new Float64Array(n);
  m[0] = secants[0];
  m[n - 1] = secants[n - 2];
  for (let i = 1; i < n - 1; i++) {
    m[i] = (secants[i - 1] + secants[i]) / 2;
  }

  for (let i = 0; i < n - 1; i++) {
    if (secants[i] === 0) {
      // A flat segment stays flat; any non-zero tangent here would bulge above
      // or below the two equal endpoints.
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }

    const alpha = m[i] / secants[i];
    const beta = m[i + 1] / secants[i];
    const magnitude = alpha * alpha + beta * beta;
    if (magnitude > MONOTONICITY_RADIUS_SQUARED) {
      const scale = 3 / Math.sqrt(magnitude);
      m[i] = scale * alpha * secants[i];
      m[i + 1] = scale * beta * secants[i];
    }
  }

  return m;
}

/** Cubic Hermite evaluation of the interpolated curve at one `x` (§6.2, step 4). */
export function evaluate(points: CurvePoints, slopes: Float64Array, x: number): number {
  // The segment containing x: the last knot whose x is not greater than the
  // sample, clamped so the ends stay on a real segment.
  let index = 0;
  for (let i = 1; i < points.length - 1; i++) {
    if (points[i][0] <= x) {
      index = i;
    }
  }

  const [x0, y0] = points[index];
  const [x1, y1] = points[index + 1];
  const m0 = slopes[index];
  const m1 = slopes[index + 1];

  const h = x1 - x0;
  const t = (x - x0) / h;
  const t2 = t * t;
  const t3 = t2 * t;

  const h00 = 2 * t3 - 3 * t2 + 1;
  const h10 = t3 - 2 * t2 + t;
  const h01 = -2 * t3 + 3 * t2;
  const h11 = t3 - t2;

  return h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1;
}

/**
 * Sample the interpolated curve at `size` evenly spaced inputs (§6.3).
 *
 * `lut[0]` and `lut[size - 1]` therefore hit the curve's endpoints exactly.
 */
export function buildLut(points: CurvePoints, size = LUT_SIZE): Float32Array {
  const slopes = tangents(points);
  const lut = new Float32Array(size);
  for (let i = 0; i < size; i++) {
    const x = i / (size - 1);
    lut[i] = Math.min(Math.max(evaluate(points, slopes, x), 0), 1);
  }
  return lut;
}

/**
 * Look up one value in the table and interpolate linearly between entries (§6.4).
 *
 * The shader does this arithmetic itself, over two `texelFetch` reads — never
 * through `GL_LINEAR`, whose interpolation weight is computed at an
 * implementation-defined precision and cannot be reproduced in NumPy (§6.5).
 * This function is the same formula on the CPU, and exists so the two can be
 * compared without a GPU.
 *
 * The input is clamped **before** the lookup: after the tone regions and contrast
 * it may sit outside [0, 1], and this is the only clamp before step 11. It
 * concerns the table index, nothing else.
 */
export function applyLut(lut: Float32Array, value: number): number {
  const size = lut.length;
  const t = Math.min(Math.max(value, 0), 1) * (size - 1);
  const index = Math.min(Math.max(Math.floor(t), 0), size - 2);
  const frac = t - index;
  return lut[index] * (1 - frac) + lut[index + 1] * frac;
}
