"""ProPhoto RGB to sRGB, for the dataset boundary (ADR-17).

Expert renditions are 16-bit ProPhoto RGB; the renderer works in sRGB and the
output of the whole system is sRGB everywhere. The conversion therefore lives
**here, at the boundary** — the renderer never sees it.

Two things it must get right, either of which poisons every measurement if wrong:

* **White point.** ProPhoto is D50, sRGB is D65. Skipping the chromatic adaptation
  leaves a warm cast on every image, which the fit would then dutifully try to
  correct with the white balance parameters.
* **Transfer function.** ProPhoto uses gamma 1.8 with a short linear toe, not
  sRGB's ~2.2. Decoding with the wrong one shifts the whole tone scale.

Gamut clipping is reported, not hidden: colours outside sRGB are unreachable by
construction, and the fit must not be blamed for them.

**Scope.** Probe-only for now. Phase 2 promotes it into the library once there is
an ingestion module to hold it — the offline pipeline needs the same conversion,
and it must not end up as a copy (`.claude/rules/pipeline.md`).
"""

import numpy as np
from numpy.typing import NDArray

# ROMM RGB (ProPhoto) primaries to XYZ, D50.
_ROMM_TO_XYZ_D50 = np.array(
    [
        [0.7976749, 0.1351917, 0.0313534],
        [0.2880402, 0.7118741, 0.0000857],
        [0.0000000, 0.0000000, 0.8252100],
    ]
)

# Bradford chromatic adaptation, D50 to D65.
_BRADFORD_D50_TO_D65 = np.array(
    [
        [0.9555766, -0.0230393, 0.0631636],
        [-0.0282895, 1.0099416, 0.0210077],
        [0.0122982, -0.0204830, 1.3299098],
    ]
)

# XYZ (D65) to linear sRGB.
_XYZ_D65_TO_SRGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ]
)

PROPHOTO_TO_SRGB_LINEAR = _XYZ_D65_TO_SRGB @ _BRADFORD_D50_TO_D65 @ _ROMM_TO_XYZ_D50

# ROMM transfer function: linear below Et, gamma 1.8 above.
_ROMM_ET = 1.0 / 512.0
_ROMM_SLOPE = 16.0
_ROMM_GAMMA = 1.8

# Guards the matrix chain at import: ProPhoto white must land on sRGB white. A
# typo in any of the three matrices, or a forgotten adaptation, breaks this.
_white = PROPHOTO_TO_SRGB_LINEAR @ np.ones(3)
if not np.allclose(_white, 1.0, atol=1e-4):  # pragma: no cover - configuration guard
    raise RuntimeError(f"ProPhoto white does not map to sRGB white: {_white}")


def romm_decode(value: NDArray[np.floating]) -> NDArray[np.float64]:
    """ProPhoto encoded values in [0, 1] to linear light."""
    x = np.asarray(value, dtype=np.float64)
    return np.where(x < _ROMM_SLOPE * _ROMM_ET, x / _ROMM_SLOPE, x**_ROMM_GAMMA)


def srgb_encode(value: NDArray[np.floating]) -> NDArray[np.float64]:
    """Linear light to sRGB, in float64 — the boundary is not the per-pixel path."""
    x = np.asarray(value, dtype=np.float64)
    safe = np.maximum(x, 0.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * safe ** (1.0 / 2.4) - 0.055)


def prophoto_to_srgb(image: NDArray[np.integer]) -> tuple[NDArray[np.float64], float]:
    """16-bit ProPhoto to linear sRGB, with the share of pixels outside the gamut.

    Returns **linear** sRGB, unclipped, so the caller can downscale in linear light
    before deciding where to clip. The reported fraction counts pixels where any
    channel left [0, 1] before clipping — those colours cannot be reproduced by
    anything working in sRGB, and the number belongs in the report next to the
    fitting error rather than inside it.
    """
    encoded = np.asarray(image, dtype=np.float64) / 65535.0
    linear_prophoto = romm_decode(encoded)
    linear_srgb = linear_prophoto @ PROPHOTO_TO_SRGB_LINEAR.T

    tolerance = 1e-6
    outside = (linear_srgb < -tolerance) | (linear_srgb > 1.0 + tolerance)
    return linear_srgb, float(outside.any(axis=-1).mean())


def _pool(x: NDArray[np.float64], target: int, axis: int) -> NDArray[np.float64]:
    """Area-average one axis down to exactly ``target`` samples."""
    length = x.shape[axis]
    starts = np.arange(target) * length // target
    counts = np.diff(np.append(starts, length))

    sums = np.add.reduceat(x, starts, axis=axis)
    shape = [1] * x.ndim
    shape[axis] = target
    return sums / counts.reshape(shape)


def resample_area(linear: NDArray[np.floating], target: tuple[int, int]) -> NDArray[np.float64]:
    """Area-average down to an exact height and width, in linear light.

    Two reasons this is not a plain integer box factor, which is what the first
    version did. It has to hit an **exact** target, because the three images being
    compared start at slightly different sizes — the raw decode keeps sensor
    border pixels that Lightroom trims — and an integer factor per image lands
    them on different grids. And it has to work for a non-integer ratio, which an
    integer factor by definition cannot.

    Linear light, not gamma: averaging encoded values darkens edges, because the
    average of two encoded values is not the encoding of their average.

    Bin edges are integers, so a bin covers 4 to 8 whole pixels at the ratios used
    here and the rounding is small and unbiased. That keeps the operation plain
    arithmetic, reproducible in any language — which matters once the WebGL side
    has to agree on how a preview was produced.
    """
    x = np.asarray(linear, dtype=np.float64)
    return _pool(_pool(x, target[0], axis=0), target[1], axis=1)
