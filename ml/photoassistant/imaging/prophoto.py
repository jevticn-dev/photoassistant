"""ProPhoto RGB to sRGB, at the dataset boundary (ADR-17).

Expert renditions are 16-bit ProPhoto RGB; the renderer works in sRGB and every
output of the system is sRGB. The conversion therefore lives **here, at the
boundary** — the renderer never sees it.

Two things it must get right, either of which poisons every measurement if wrong:

* **White point.** ProPhoto is D50, sRGB is D65. Skipping the chromatic adaptation
  leaves a cast on every image, which the fit would then dutifully try to correct
  with the white balance parameters — turning a colour-space error into what
  looks like a model result.
* **Transfer function.** ProPhoto uses gamma 1.8 with a short linear toe, not
  sRGB's piecewise ~2.2. Decoding with the wrong one shifts the whole tone scale.

Gamut clipping is reported, not hidden: colours outside sRGB are unreachable by
construction, and the fit must not be blamed for them (ADR-17).

Promoted from ``pipeline/probe/prophoto.py`` in phase 2: the offline pipeline and
the phase 5 RAW path need the same conversion, and it must exist once
(`.claude/rules/pipeline.md`).
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


# The sRGB transfer function deliberately does **not** live here. The probe
# carried its own float64 copy, which was right for a throwaway script and wrong
# for a library: two implementations of one formula is how they drift. The single
# one is photoassistant.renderer.color.srgb_encode, working in float32 — far
# finer than the 8-bit quantisation every derivative ends at, where one step is
# 1/255 and float32 resolves about a millionth of that.


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


