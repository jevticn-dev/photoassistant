"""Weight functions for the four tone regions.

Implements ``RENDERER_SPEC.md`` §7. A pixel carries no label saying which part of
the tonal range it belongs to, so the regions are expressed as weights over luma:
``w(Y')`` is the **share** of the pixel that belongs to a region, not a verdict.

That partial membership is what makes the result smooth. A hard threshold
(``if Y' < 0.25 then blacks``) would give two pixels at 0.249 and 0.251 entirely
different treatment, and a gradient would show a visible band at exactly that
luma. Two regions sharing an end of the range hand the weight over gradually:
``w_blacks + w_shadows`` is exactly 1 across [0, 0.25], and the same holds for
highlights and whites across [0.75, 1].

Known limit, stated in the spec (§7.4) and worth repeating where the code lives:
Lightroom's masks are content-adaptive — they look at a pixel's neighbourhood —
while these are pure functions of the pixel's own luma. Fitting in phase 2 will
therefore not reproduce an expert edit exactly. The master curve absorbs most of
the remainder, and what is left is measured and reported rather than assumed away.
"""

import numpy as np
from numpy.typing import NDArray

# Breakpoints of the four windows (spec §7.2).
_BLACKS_END = 0.25
_SHADOWS_END = 0.60
_HIGHLIGHTS_START = 0.40
_WHITES_START = 0.75


def smoothstep(
    edge0: float, edge1: float, x: NDArray[np.floating]
) -> NDArray[np.float32]:
    """``t^2 (3 - 2t)`` clamped to the edges — the smooth building block.

    C1 continuous at both ends, which is the property that keeps a mask from
    leaving a visible contour along a line of constant luma. Also polynomial,
    so it costs nothing in agreement: no transcendental function whose last bits
    differ between NumPy and GLSL.
    """
    t = np.clip(
        (np.asarray(x, dtype=np.float32) - np.float32(edge0)) / np.float32(edge1 - edge0),
        np.float32(0.0),
        np.float32(1.0),
    )
    return (t * t * (np.float32(3.0) - np.float32(2.0) * t)).astype(np.float32)


def blacks(y: NDArray[np.floating]) -> NDArray[np.float32]:
    return (np.float32(1.0) - smoothstep(0.0, _BLACKS_END, y)).astype(np.float32)


def shadows(y: NDArray[np.floating]) -> NDArray[np.float32]:
    rising = smoothstep(0.0, _BLACKS_END, y)
    falling = np.float32(1.0) - smoothstep(_BLACKS_END, _SHADOWS_END, y)
    return (rising * falling).astype(np.float32)


def highlights(y: NDArray[np.floating]) -> NDArray[np.float32]:
    rising = smoothstep(_HIGHLIGHTS_START, _WHITES_START, y)
    falling = np.float32(1.0) - smoothstep(_WHITES_START, 1.0, y)
    return (rising * falling).astype(np.float32)


def whites(y: NDArray[np.floating]) -> NDArray[np.float32]:
    return smoothstep(_WHITES_START, 1.0, y)
