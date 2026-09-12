"""Imaging — what happens at the edges of the renderer, not inside it.

Three things live here, and they share one property: the renderer must not see any
of them. It takes an sRGB float array and returns one; how that array came to
exist, and what is written out afterwards, is this module's business.

``prophoto``
    ProPhoto RGB to sRGB, with the D50 to D65 chromatic adaptation. The dataset's
    expert renditions are 16-bit ProPhoto; the whole system is sRGB (ADR-17). The
    share of pixels that leave the sRGB gamut is **reported, not hidden** — those
    colours are unreachable by construction and the fit must not be blamed for
    them.

``resample``
    Area averaging down to an exact size, in linear light.

``derivatives``
    The two sizes the project stores: 512px for fitting and fingerprints, 2048px
    for the editor's live preview (ADR-3b).

Why not inside ``renderer/``: ADR-17 puts the colour-space conversion **at the
boundary towards the dataset**, and the renderer's own contract is that it works
in one space start to finish. Filing this under ``renderer`` would be the first
step towards it being called from inside one.
"""

from photoassistant.imaging.derivatives import (
    FIT_SIZE,
    PROXY_SIZE,
    Derivative,
    Derivatives,
    encode_jpeg,
    encode_png,
    fit_size_for,
    make_derivatives,
)
from photoassistant.imaging.prophoto import (
    PROPHOTO_TO_SRGB_LINEAR,
    prophoto_to_srgb,
    romm_decode,
)
from photoassistant.imaging.resample import resample_area

__all__ = [
    "FIT_SIZE",
    "PROPHOTO_TO_SRGB_LINEAR",
    "PROXY_SIZE",
    "Derivative",
    "Derivatives",
    "encode_jpeg",
    "encode_png",
    "fit_size_for",
    "make_derivatives",
    "prophoto_to_srgb",
    "resample_area",
    "romm_decode",
]
