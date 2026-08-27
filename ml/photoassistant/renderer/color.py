"""Colour spaces and the colour-difference metric.

Two separate jobs live here.

**Transfer function and luma** belong to the renderer: they implement
``RENDERER_SPEC.md`` §2 and run inside the per-pixel path, in ``float32``.

**CIELAB and CIEDE2000** are the *measuring instrument*, not part of rendering.
They answer "how different do these two images look", which is what the golden
agreement test asserts and what phase 2 minimises while fitting. Being the ruler,
they compute in ``float64``: the spec's ``float32`` contract (§8.1) is about the
two renderer implementations agreeing with each other, and deliberately does not
apply to the tool that measures them.

The implementation is written out rather than imported. ``scikit-image`` has
``deltaE_ciede2000``, but it arrives with ``scipy``, ``networkx``, ``imageio`` and
``tifffile``, three of which this project will never otherwise need — and sRGB to
Lab is required regardless, for phase 2. The risk that comes with writing it by
hand is bounded the only way that counts: ``test_colour_difference.py`` runs the
34 published pairs from Sharma et al. (2005) through it. A library taken on trust
and not checked against those pairs would be the weaker position, not the safer
one.
"""

import numpy as np
from numpy.typing import NDArray

# sRGB, IEC 61966-2-1. Piecewise by definition; a plain 2.2 power is not a
# substitute (RENDERER_SPEC.md §2.1).
_SRGB_LINEAR_SLOPE = 12.92
_SRGB_DECODE_THRESHOLD = 0.04045
_SRGB_ENCODE_THRESHOLD = 0.0031308
_SRGB_OFFSET = 0.055
_SRGB_SCALE = 1.055
_SRGB_GAMMA = 2.4

# Rec.709 luma weights, applied to gamma-encoded values (spec §2.2).
LUMA_WEIGHTS = (0.2126, 0.7152, 0.0722)

# CIE standard illuminant D65, 2-degree observer.
_D65_WHITE = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)

# sRGB primaries to XYZ, D65 adapted.
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)

# CIELAB f(t) breakpoint: delta = 6/29.
_LAB_DELTA = 6.0 / 29.0


def srgb_decode(value: NDArray[np.floating]) -> NDArray[np.float32]:
    """sRGB to linear light, per channel (spec §2.1).

    Defined for ``value >= 0``. Values above 1 are carried through: exposure may
    push past white and only step 11 clips.
    """
    x = np.asarray(value, dtype=np.float32)
    below = x / np.float32(_SRGB_LINEAR_SLOPE)
    above = ((x + np.float32(_SRGB_OFFSET)) / np.float32(_SRGB_SCALE)) ** np.float32(_SRGB_GAMMA)
    return np.where(x <= np.float32(_SRGB_DECODE_THRESHOLD), below, above).astype(np.float32)


def srgb_encode(value: NDArray[np.floating]) -> NDArray[np.float32]:
    """Linear light to sRGB, per channel (spec §2.1).

    The formula continues analytically above 1 and is **not** clipped here.
    Clipping it at this point would throw away the highlight headroom that a
    negative ``highlights`` is meant to recover.
    """
    x = np.asarray(value, dtype=np.float32)
    below = np.float32(_SRGB_LINEAR_SLOPE) * x
    # Guard the fractional power against a negative base. Negatives cannot occur
    # in the pipeline — white balance and exposure are multiplications by
    # positive numbers — but a stray one would produce NaN instead of an error.
    safe = np.maximum(x, np.float32(0.0))
    above = np.float32(_SRGB_SCALE) * safe ** np.float32(1.0 / _SRGB_GAMMA) - np.float32(
        _SRGB_OFFSET
    )
    return np.where(x <= np.float32(_SRGB_ENCODE_THRESHOLD), below, above).astype(np.float32)


def luma(image: NDArray[np.floating]) -> NDArray[np.float32]:
    """Rec.709 luma of gamma-encoded RGB (spec §2.2).

    Luma, written ``Y'``, not luminance: the same weights over *linear* values
    would be luminance, and the two differ. The operations that consume this run
    in gamma space, so gamma-encoded input is the right one.
    """
    rgb = np.asarray(image, dtype=np.float32)
    weights = np.array(LUMA_WEIGHTS, dtype=np.float32)
    return (rgb * weights).sum(axis=-1, dtype=np.float32)


def srgb_to_lab(image: NDArray[np.floating]) -> NDArray[np.float64]:
    """sRGB in [0, 1] to CIELAB, D65.

    Runs in ``float64``: this feeds the measurement, not the render.
    """
    rgb = np.asarray(image, dtype=np.float64)

    # Decode in float64 as well, so the ruler does not inherit float32 rounding.
    below = rgb / _SRGB_LINEAR_SLOPE
    above = ((rgb + _SRGB_OFFSET) / _SRGB_SCALE) ** _SRGB_GAMMA
    linear = np.where(rgb <= _SRGB_DECODE_THRESHOLD, below, above)

    xyz = linear @ _RGB_TO_XYZ.T
    scaled = xyz / _D65_WHITE

    # f(t): cube root above the breakpoint, linear below, so the derivative stays
    # finite at zero.
    cube_root = np.cbrt(scaled)
    linear_part = scaled / (3.0 * _LAB_DELTA**2) + 4.0 / 29.0
    f = np.where(scaled > _LAB_DELTA**3, cube_root, linear_part)

    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack(
        [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)],
        axis=-1,
    )


def ciede2000(lab1: NDArray[np.floating], lab2: NDArray[np.floating]) -> NDArray[np.float64]:
    """CIEDE2000 colour difference, with k_L = k_C = k_H = 1.

    Follows CIE 142:2001 as documented by Sharma, Wu & Dalal (2005), whose
    implementation notes exist because a naive reading gets the hue arithmetic
    wrong. The two places that bite:

    * the mean hue is a **sum**, not an average, when either chroma is zero
    * hue differences wrap at 360 degrees, and the wrap has to be applied before
      the mean, not after
    """
    a = np.asarray(lab1, dtype=np.float64)
    b = np.asarray(lab2, dtype=np.float64)

    l1, a1, b1 = a[..., 0], a[..., 1], a[..., 2]
    l2, a2, b2 = b[..., 0], b[..., 1], b[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0

    # G stretches a* for low-chroma colours, which is what fixes CIELAB's poor
    # behaviour near the neutral axis.
    c_bar7 = c_bar**7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))

    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    # arctan2(0, 0) is 0, which is the value the standard prescribes for an
    # achromatic colour, so no special case is needed here.

    delta_l = l2 - l1
    delta_c = c2p - c1p

    chroma_product = c1p * c2p

    # Wrap the hue difference into (-180, 180]: going from 350 to 10 degrees is a
    # step of +20, not -340. Applying this before the mean hue below is the whole
    # point of the implementation notes.
    raw_delta_h = h2p - h1p
    wrapped = np.where(raw_delta_h > 180.0, raw_delta_h - 360.0, raw_delta_h)
    wrapped = np.where(wrapped < -180.0, wrapped + 360.0, wrapped)
    delta_h = np.where(chroma_product == 0.0, 0.0, wrapped)

    delta_hp = 2.0 * np.sqrt(chroma_product) * np.sin(np.radians(delta_h) / 2.0)

    l_bar = (l1 + l2) / 2.0
    c_barp = (c1p + c2p) / 2.0

    h_sum = h1p + h2p
    h_barp = np.where(
        chroma_product == 0.0,
        h_sum,
        np.where(
            np.abs(h1p - h2p) <= 180.0,
            h_sum / 2.0,
            np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
        ),
    )

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_barp - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_barp))
        + 0.32 * np.cos(np.radians(3.0 * h_barp + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_barp - 63.0))
    )

    delta_theta = 30.0 * np.exp(-(((h_barp - 275.0) / 25.0) ** 2))
    c_barp7 = c_barp**7
    r_c = 2.0 * np.sqrt(c_barp7 / (c_barp7 + 25.0**7))

    s_l = 1.0 + (0.015 * (l_bar - 50.0) ** 2) / np.sqrt(20.0 + (l_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_barp
    s_h = 1.0 + 0.015 * c_barp * t
    r_t = -np.sin(np.radians(2.0 * delta_theta)) * r_c

    term_l = delta_l / s_l
    term_c = delta_c / s_c
    term_h = delta_hp / s_h

    return np.sqrt(term_l**2 + term_c**2 + term_h**2 + r_t * term_c * term_h)


def delta_e(image1: NDArray[np.floating], image2: NDArray[np.floating]) -> NDArray[np.float64]:
    """Per-pixel CIEDE2000 between two sRGB images in [0, 1]."""
    return ciede2000(srgb_to_lab(image1), srgb_to_lab(image2))
