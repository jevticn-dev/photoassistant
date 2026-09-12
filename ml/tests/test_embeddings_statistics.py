"""Colour statistics — the seventeen numbers that describe what an edit did.

Each test here exists because one component of the vector was argued for. If the
argument is right, a synthetic edit that exercises exactly that property must move
exactly that component — and the tests that matter most are the two that justify
components which are not obviously needed: mean chroma, and the four that measure
shadows and highlights separately.
"""

import numpy as np
import pytest

from photoassistant.embeddings.statistics import (
    STATISTIC_COUNT,
    STATISTIC_NAMES,
    colour_statistics,
    statistics_difference,
)


def index_of(name: str) -> int:
    return STATISTIC_NAMES.index(name)


def uniform(value: tuple[float, float, float], size: int = 32) -> np.ndarray:
    return np.tile(np.array(value, dtype=np.float64), (size, size, 1))


def split_image(
    dark: tuple[float, float, float], bright: tuple[float, float, float], size: int = 32
) -> np.ndarray:
    """An image whose top half is one colour and bottom half another."""
    image = np.empty((size, size, 3), dtype=np.float64)
    image[: size // 2] = np.array(dark, dtype=np.float64)
    image[size // 2 :] = np.array(bright, dtype=np.float64)
    return image


def test_layout_is_the_documented_one() -> None:
    """The order is a contract: the column's dimension is derived from it."""
    assert STATISTIC_COUNT == 17
    assert len(set(STATISTIC_NAMES)) == STATISTIC_COUNT
    assert colour_statistics(uniform((0.5, 0.5, 0.5))).shape == (STATISTIC_COUNT,)


def test_an_image_against_itself_has_no_difference() -> None:
    image = split_image((0.15, 0.2, 0.3), (0.8, 0.75, 0.6))

    assert np.allclose(statistics_difference(image, image), 0.0)


def test_brightening_lifts_every_lightness_percentile() -> None:
    before = uniform((0.3, 0.3, 0.3))
    after = uniform((0.6, 0.6, 0.6))

    difference = statistics_difference(before, after)

    percentiles = [
        difference[index_of(name)] for name in STATISTIC_NAMES if name.startswith("lightness_p")
    ]
    assert all(value > 0.0 for value in percentiles)
    assert difference[index_of("lightness_mean")] > 0.0


def test_raising_contrast_spreads_the_ends_apart() -> None:
    """What a mean cannot see, and the reason there are seven percentiles.

    The two halves move in opposite directions by the same amount, so the mean
    barely shifts while the distribution gets visibly wider.
    """
    before = split_image((0.4, 0.4, 0.4), (0.6, 0.6, 0.6))
    after = split_image((0.25, 0.25, 0.25), (0.78, 0.78, 0.78))

    difference = statistics_difference(before, after)

    assert difference[index_of("lightness_p5")] < -5.0
    assert difference[index_of("lightness_p95")] > 5.0
    assert abs(difference[index_of("lightness_mean")]) < 3.0
    assert difference[index_of("lightness_std")] > 5.0


def test_mean_chroma_sees_colour_that_the_a_and_b_means_cancel_out() -> None:
    """Why C* is carried even though it is derived from a* and b*.

    Strong red against strong green averages to nearly neutral on the a* axis —
    numerically close to a grey image. Mean chroma tells them apart, and without
    it "the expert boosted every colour" would look like "the expert left colour
    alone" (§A15).
    """
    grey = uniform((0.5, 0.5, 0.5))
    colourful = split_image((0.75, 0.2, 0.2), (0.2, 0.6, 0.2))

    difference = statistics_difference(grey, colourful)

    chroma = difference[index_of("chroma_mean")]
    assert chroma > 20.0
    assert abs(difference[index_of("a_mean")]) < 0.5 * chroma
    assert difference[index_of("chroma_p90")] > 20.0


def test_split_toning_shows_up_only_when_the_ends_are_measured_separately() -> None:
    """The test that justifies the last four components.

    The edit pushes shadows towards blue and highlights towards yellow — the
    classic split tone, which edit schema v1 cannot express at all. Over the whole
    image the two shifts very nearly cancel; measured at the two ends they point
    in opposite directions (§A16).
    """
    before = split_image((0.2, 0.2, 0.2), (0.75, 0.75, 0.75))
    after = split_image((0.18, 0.19, 0.30), (0.80, 0.78, 0.62))

    difference = statistics_difference(before, after)

    whole_image = difference[index_of("b_mean")]
    shadows = difference[index_of("shadow_b_mean")]
    highlights = difference[index_of("highlight_b_mean")]

    # Blue is negative b*, yellow positive. The ends must disagree in sign.
    assert shadows < -5.0
    assert highlights > 5.0
    # And the whole-image mean must be far smaller than either, which is the
    # entire reason the ends are measured separately.
    assert abs(whole_image) < 0.5 * min(abs(shadows), abs(highlights))


def test_a_wrongly_shaped_image_is_refused() -> None:
    with pytest.raises(ValueError, match="height x width x 3"):
        colour_statistics(np.zeros((4, 4), dtype=np.float64))


def test_values_outside_the_range_are_clipped_rather_than_refused() -> None:
    """A rendered image may keep highlight headroom above 1 (spec §5).

    Lab is only defined on the display range, so such an image is clipped rather
    than rejected — the alternative is a caller that has to remember to clip, and
    one that forgets gets nonsense instead of an error.
    """
    overflowing = uniform((1.4, 1.4, 1.4))

    assert np.allclose(colour_statistics(overflowing), colour_statistics(uniform((1.0, 1.0, 1.0))))
