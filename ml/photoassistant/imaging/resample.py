"""Downscaling in linear light, to an exact size.

Two operations that look like one, and are not: the pipeline stores a 512px image
for fitting and a 2048px one for the editor, and both start from the same
full-resolution rendition.

**Linear light, not gamma.** Averaging encoded values darkens edges, because the
average of two encoded values is not the encoding of their average. A thin bright
line on a dark ground loses brightness as it shrinks, and the error grows with the
contrast in the image — exactly where a photograph has detail.

Promoted from ``pipeline/probe/prophoto.py`` in phase 2.
"""

import numpy as np
from numpy.typing import NDArray


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
