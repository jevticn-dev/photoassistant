"""Rendering a recipe over a full-resolution photograph, a band at a time.

**Why not simply call ``render`` on the whole array.** Measured on this machine,
a recipe with every step active over a photograph of 48 megapixels peaks at
**4572 MB**; 24 megapixels — an ordinary camera — peaks at **2306 MB**. The file
on disk is a tenth of that: a JPEG is a compressed thing, and what a render costs
is ``pixels x channels x 4 bytes`` for every intermediate array alive at once,
which for eleven pipeline steps is several (§B121). The export runs inside the ML
service, which is already holding CLIP, so that is not a theoretical ceiling.

**Why bands are exact rather than an approximation.** Every operation in
``render`` reads one pixel and writes that pixel: white balance multiplies,
exposure scales, the tone curve is a lookup, the region masks are computed from
*that pixel's* luma. Nothing convolves, nothing looks at a neighbour, nothing
needs a statistic over the image. A band therefore has everything it needs, and
the result is identical bit for bit — proven by ``test_export.py`` rather than
asserted here.

Measured the same way, in bands of 256 rows: **518 MB** at 48 megapixels and
**329 MB** at 24, of which the input and the output arrays are most of it and
cannot be avoided. Time is unchanged (11.8 s against 12.3 s at 48 megapixels).
"""

import numpy as np
from numpy.typing import NDArray

from photoassistant.renderer import quantise, render
from photoassistant.schema import EditRecipe

DEFAULT_BAND_ROWS = 256
"""Rows rendered at once.

Chosen from the measurement rather than by feel: at 48 megapixels, 256 rows peak
at 518 MB and 64 rows at 365 MB, against 4572 MB for the whole image. The
remaining difference between band sizes is small because the input and output
arrays dominate, so this sits where the gain has flattened and the Python loop is
still short.
"""


def render_full_resolution(
    pixels: NDArray[np.uint8],
    recipe: EditRecipe,
    *,
    band_rows: int = DEFAULT_BAND_ROWS,
) -> NDArray[np.uint8]:
    """Apply ``recipe`` to an 8-bit sRGB image, returning 8-bit sRGB.

    Takes and returns ``uint8`` rather than float, which is the point: the
    caller never holds a float copy of the whole photograph, and neither does
    this. Each band is converted, rendered and quantised on its own.

    The output is identical to ``quantise(render(pixels / 255, recipe))`` for any
    ``band_rows``, and that is a test rather than a promise.
    """
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError(f"expected an (h, w, 3) image, got {pixels.shape}")
    if band_rows < 1:
        raise ValueError(f"band_rows must be at least 1, got {band_rows}")

    height = pixels.shape[0]
    out = np.empty(pixels.shape, dtype=np.uint8)

    for top in range(0, height, band_rows):
        band = pixels[top : top + band_rows].astype(np.float32) / np.float32(255.0)
        out[top : top + band_rows] = quantise(render(band, recipe))

    return out
