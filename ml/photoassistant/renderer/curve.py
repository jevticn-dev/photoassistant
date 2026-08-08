"""The master tone curve: monotone interpolation and its 1024-entry LUT.

Implements ``RENDERER_SPEC.md`` §6. The interesting part is not the maths but why
the table exists at all.

Monotone cubic interpolation is the most delicate step in the renderer — tangent
choice, the monotonicity correction, endpoint handling, each a place where two
implementations drift apart without anyone noticing. Evaluating it per pixel
would spread that risk over every pixel of every image.

The LUT collapses it: the awkward work runs **1024 times in total**, and the
per-pixel path becomes an index and a lerp, which is hard to get wrong in two
languages at once. It also makes agreement directly testable — two arrays of 1024
numbers can be compared element by element, with no image involved.

Precision note. The table is built in ``float64`` and stored as ``float32``. That
is not a departure from the spec's ``float32`` contract (§8.1), which governs the
per-pixel path: the WebGL side will build its table in JavaScript, where every
number is a double, and upload it as a ``float32`` texture. Matching that keeps
the two tables comparable. The build is 1024 evaluations, not per-pixel work, so
the cost is irrelevant either way.
"""

import numpy as np
from numpy.typing import NDArray

LUT_SIZE = 1024

# Fritsch-Carlson: tangents stay inside a circle of radius 3 around the secant.
# Proven sufficient for monotonicity, not a heuristic.
_MONOTONICITY_RADIUS_SQUARED = 9.0


def tangents(points: NDArray[np.float64]) -> NDArray[np.float64]:
    """Slopes at each control point, corrected so the curve cannot overshoot.

    Three steps, in the order the spec fixes them (§6.2): secant slopes, then a
    three-point average for the interior tangents, then the Fritsch-Carlson
    correction applied segment by segment in increasing order. The order is part
    of the specification — a correction on one segment is visible to the next.
    """
    x = points[:, 0]
    y = points[:, 1]
    n = len(points)

    secants = np.diff(y) / np.diff(x)

    m = np.empty(n, dtype=np.float64)
    m[0] = secants[0]
    m[-1] = secants[-1]
    if n > 2:
        m[1:-1] = (secants[:-1] + secants[1:]) / 2.0

    for i in range(n - 1):
        if secants[i] == 0.0:
            # A flat segment stays flat; any non-zero tangent here would bulge
            # above or below the two equal endpoints.
            m[i] = 0.0
            m[i + 1] = 0.0
            continue

        alpha = m[i] / secants[i]
        beta = m[i + 1] / secants[i]
        magnitude = alpha * alpha + beta * beta
        if magnitude > _MONOTONICITY_RADIUS_SQUARED:
            scale = 3.0 / np.sqrt(magnitude)
            m[i] = scale * alpha * secants[i]
            m[i + 1] = scale * beta * secants[i]

    return m


def evaluate(
    points: NDArray[np.float64],
    slopes: NDArray[np.float64],
    x: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Cubic Hermite evaluation of the interpolated curve at arbitrary ``x``."""
    xs = points[:, 0]
    ys = points[:, 1]

    # Segment index for each sample: searchsorted gives the first knot strictly
    # greater than x, so subtracting one lands on the segment containing it.
    index = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, len(xs) - 2)

    x0, x1 = xs[index], xs[index + 1]
    y0, y1 = ys[index], ys[index + 1]
    m0, m1 = slopes[index], slopes[index + 1]

    h = x1 - x0
    t = (x - x0) / h
    t2 = t * t
    t3 = t2 * t

    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2

    return h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1


def build_lut(points: NDArray[np.floating], size: int = LUT_SIZE) -> NDArray[np.float32]:
    """Sample the interpolated curve at ``size`` evenly spaced inputs (§6.3).

    ``lut[0]`` and ``lut[-1]`` therefore hit the curve's endpoints exactly.
    """
    control = np.asarray(points, dtype=np.float64)
    slopes = tangents(control)

    x = np.linspace(0.0, 1.0, size, dtype=np.float64)
    return np.clip(evaluate(control, slopes, x), 0.0, 1.0).astype(np.float32)


def apply_lut(lut: NDArray[np.float32], values: NDArray[np.floating]) -> NDArray[np.float32]:
    """Look up each value in the table and interpolate linearly between entries (§6.4).

    The input is clipped **before** the lookup: after the tone regions and
    contrast it may sit outside [0, 1], and this is the only clip before step 11.
    It concerns the table index, nothing else.
    """
    x = np.asarray(values, dtype=np.float32)
    size = len(lut)

    t = np.clip(x, np.float32(0.0), np.float32(1.0)) * np.float32(size - 1)
    index = np.clip(np.floor(t).astype(np.int32), 0, size - 2)
    frac = (t - index).astype(np.float32)

    return (lut[index] * (np.float32(1.0) - frac) + lut[index + 1] * frac).astype(np.float32)


def is_identity(points: NDArray[np.floating]) -> bool:
    """True for the neutral curve, the diagonal through (0,0) and (1,1)."""
    control = np.asarray(points, dtype=np.float64)
    return control.shape == (2, 2) and bool(
        np.array_equal(control, np.array([[0.0, 0.0], [1.0, 1.0]]))
    )
