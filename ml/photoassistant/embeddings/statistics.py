"""Colour statistics of one image, and the difference between two of them.

These seventeen numbers are the second half of the style fingerprint. They answer
"what happened to the image", where the fitted recipe answers "what did the expert
set". Both are needed because the same setting does not have the same effect on
every photograph: ``contrast = 30`` rescues a flat, hazy frame and wrecks an
already contrasty one.

Everything is measured in **CIELAB**, not in RGB. Lab is built so that distance
approximates perceived difference, and its axes are the opponent pairs the visual
system actually uses — ``L*`` light/dark, ``a*`` green/red, ``b*`` blue/yellow.
An RGB mean would describe the display, not the impression. See
``docs/notes/phase-2-concepts.md`` §A15 and phase 1 §B6.

**The layout is a contract.** The order below is written into every fingerprint in
the database, and the migration fixes the column's dimension from it. Adding a
statistic is therefore not a local change: it is a new dimension, a new migration
and a recomputation of every row. Appending to the end costs least, but nothing
here is free — which is the point of settling it once.
"""

from typing import Final

import numpy as np
from numpy.typing import NDArray

from photoassistant.renderer.color import srgb_to_lab

# Where the lightness distribution is sampled. Seven rather than one because each
# tonal control moves its own part of the histogram: a mean survives an edit that
# lifts the shadows and drops the highlights almost unchanged, while p5 and p95
# move in opposite directions (§B42).
LIGHTNESS_PERCENTILES: Final[tuple[float, ...]] = (1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0)

# The quantile that splits "shadows" from the rest, and its mirror for highlights.
# Chosen to match the percentiles above rather than invented separately, so the
# split is at a point the vector already describes.
SHADOW_QUANTILE: Final[float] = 25.0
HIGHLIGHT_QUANTILE: Final[float] = 75.0

# Where the chroma distribution is sampled, on top of its mean. p90 rather than
# the maximum: the maximum is one pixel and a single specular highlight would own
# it, while p90 describes the colourful part of the image.
CHROMA_PERCENTILE: Final[float] = 90.0

# The order is the contract. Read by fingerprint.py, reported by the pipeline, and
# the reason the fingerprint column has the dimension it has.
STATISTIC_NAMES: Final[tuple[str, ...]] = (
    "lightness_p1",
    "lightness_p5",
    "lightness_p25",
    "lightness_p50",
    "lightness_p75",
    "lightness_p95",
    "lightness_p99",
    "lightness_mean",
    "lightness_std",
    "a_mean",
    "b_mean",
    "chroma_mean",
    "chroma_p90",
    "shadow_a_mean",
    "shadow_b_mean",
    "highlight_a_mean",
    "highlight_b_mean",
)

STATISTIC_COUNT: Final[int] = len(STATISTIC_NAMES)


def colour_statistics(srgb: NDArray[np.floating]) -> NDArray[np.float64]:
    """Seventeen numbers describing one sRGB image, in ``STATISTIC_NAMES`` order.

    ``srgb`` is height x width x 3 in [0, 1]. Values outside that range are not
    rejected — the caller may hand over a rendered image that kept its highlight
    headroom — but Lab is only meaningful inside it, so they are clipped first.
    """
    image = np.asarray(srgb, dtype=np.float64)
    if image.ndim != 3 or image.shape[-1] != 3:
        raise ValueError(f"expected a height x width x 3 image, got shape {image.shape}")

    lab = srgb_to_lab(np.clip(image, 0.0, 1.0))
    lightness = lab[..., 0].reshape(-1)
    a = lab[..., 1].reshape(-1)
    b = lab[..., 2].reshape(-1)

    # Chroma is distance from grey in the a*/b* plane. It is not a fourth
    # independent measurement — it is derived from the two — but it is carried
    # separately because the means of a* and b* cancel: an image with strong reds
    # and strong greens averages to nearly zero on a*, exactly like a grey image.
    # Mean chroma tells the two apart (§A15).
    chroma = np.hypot(a, b)

    percentiles = np.percentile(lightness, LIGHTNESS_PERCENTILES)

    shadow_limit = float(np.percentile(lightness, SHADOW_QUANTILE))
    highlight_limit = float(np.percentile(lightness, HIGHLIGHT_QUANTILE))
    shadows = lightness <= shadow_limit
    highlights = lightness >= highlight_limit

    return np.array(
        [
            *percentiles,
            lightness.mean(),
            lightness.std(),
            a.mean(),
            b.mean(),
            chroma.mean(),
            np.percentile(chroma, CHROMA_PERCENTILE),
            # The last four are what catches split toning: shadows pushed one way
            # and highlights the other. Over the whole image such an edit almost
            # cancels — measured separately, the two ends move in opposite
            # directions. Schema v1 cannot express this, which is exactly why it
            # has to be measured rather than inferred from the recipe (§A16).
            _masked_mean(a, shadows),
            _masked_mean(b, shadows),
            _masked_mean(a, highlights),
            _masked_mean(b, highlights),
        ],
        dtype=np.float64,
    )


def statistics_difference(
    before: NDArray[np.floating], after: NDArray[np.floating]
) -> NDArray[np.float64]:
    """``colour_statistics(after) - colour_statistics(before)``.

    Both images are real files from the dataset — the neutral rendition and the
    expert's result. Our own reconstruction takes no part in this: it is measured
    separately as ``examples.fit_error`` and answers a different question (§B49).
    """
    return colour_statistics(after) - colour_statistics(before)


def _masked_mean(values: NDArray[np.float64], mask: NDArray[np.bool_]) -> float:
    """Mean over the selected pixels, falling back to the whole image if none are.

    The masks come from percentiles of the same data, so at least the darkest
    pixel always satisfies the shadow one — an empty selection needs a degenerate
    input to happen at all. The guard is here so that such an input returns a
    number rather than a NaN that would then spread through the scaling constants
    and quietly poison every fingerprint in the corpus.
    """
    if not mask.any():
        return float(values.mean())
    return float(values[mask].mean())
