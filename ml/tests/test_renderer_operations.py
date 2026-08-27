"""One test per parameter: does the operation do what its stated intent promises?

``RENDERER_SPEC.md`` §3 opens every parameter with a one-sentence statement of
intent, and the rule there is that **the intent is authoritative** — if formula
and intent disagree, the formula is wrong. These tests assert the intent, so the
two cannot drift apart silently.
"""

import numpy as np
import pytest

from photoassistant.renderer.color import luma, srgb_decode
from photoassistant.renderer.pipeline import (
    apply_contrast,
    apply_saturation,
    render,
    tone_region_shift,
    white_balance_multipliers,
)
from photoassistant.schema import EditRecipe

MID_GREY = np.array([[[0.5, 0.5, 0.5]]], dtype=np.float32)


def recipe(**values: float) -> EditRecipe:
    """Build a recipe from flat keyword arguments, everything else neutral."""
    groups: dict[str, dict[str, float]] = {"white_balance": {}, "tone": {}, "color": {}}
    where = {
        "temperature": "white_balance",
        "tint": "white_balance",
        "exposure": "tone",
        "contrast": "tone",
        "highlights": "tone",
        "shadows": "tone",
        "whites": "tone",
        "blacks": "tone",
        "saturation": "color",
        "vibrance": "color",
    }
    for key, value in values.items():
        groups[where[key]][key] = value
    return EditRecipe.model_validate({"schema": 1, **groups})


# --------------------------------------------------------------------- 3.1 WB


def test_white_balance_does_not_change_brightness() -> None:
    """Intent: shift the colour balance, leave overall brightness to exposure."""
    for temperature, tint in ((100.0, 0.0), (-100.0, 0.0), (0.0, 100.0), (60.0, -40.0)):
        multipliers = white_balance_multipliers(temperature, tint)
        weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

        assert float((multipliers * weights).sum()) == pytest.approx(1.0, abs=1e-6)


def test_white_balance_warms_towards_red_and_away_from_blue() -> None:
    warm = white_balance_multipliers(100.0, 0.0)
    cool = white_balance_multipliers(-100.0, 0.0)

    assert warm[0] > warm[2], "positive temperature must favour red over blue"
    assert cool[0] < cool[2]

    # At the range limit the red-to-blue ratio is 2^(2 * K_WB) = 8. It was 2 until
    # the phase 1b probe showed that too narrow to express a tungsten-to-daylight
    # correction, and the fit drained saturation instead (ADR-19).
    assert float(warm[0] / warm[2]) == pytest.approx(8.0, abs=1e-4)


def test_tint_moves_along_the_green_magenta_axis() -> None:
    magenta = white_balance_multipliers(0.0, 100.0)

    assert magenta[1] < magenta[0], "positive tint must cut green"
    assert float(magenta[0]) == pytest.approx(float(magenta[2]), abs=1e-6)


def test_neutral_white_balance_is_the_identity() -> None:
    assert white_balance_multipliers(0.0, 0.0) == pytest.approx([1.0, 1.0, 1.0], abs=1e-6)


# --------------------------------------------------------------- 3.2 exposure


def test_one_stop_is_twice_the_light() -> None:
    """Intent: +1 means double the light, as on a camera."""
    before = np.array([[[0.2, 0.2, 0.2]]], dtype=np.float32)

    after = render(before, recipe(exposure=1.0))

    linear_before = float(srgb_decode(before[0, 0, 0]))
    linear_after = float(srgb_decode(after[0, 0, 0]))
    assert linear_after == pytest.approx(2.0 * linear_before, rel=1e-4)


def test_exposure_leaves_the_colour_ratios_alone() -> None:
    before = np.array([[[0.30, 0.15, 0.08]]], dtype=np.float32)

    after = render(before, recipe(exposure=0.5))

    ratio_before = srgb_decode(before) / srgb_decode(before)[..., :1]
    ratio_after = srgb_decode(after) / srgb_decode(after)[..., :1]
    assert ratio_after == pytest.approx(ratio_before, abs=1e-4)


# ---------------------------------------------------------- 3.3 tone regions


def test_blacks_lifts_the_dark_end_and_leaves_the_rest() -> None:
    """Intent: brighten or darken only part of the range, midtones largely untouched."""
    wedge = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    image = np.repeat(wedge[:, np.newaxis], 3, axis=1)[np.newaxis, ...]

    shift = tone_region_shift(image, recipe(blacks=100.0))[0]

    assert float(shift[0]) == pytest.approx(0.25, abs=1e-5), "full lift at black"
    assert float(shift[-1]) == pytest.approx(0.0, abs=1e-6), "nothing at white"
    assert float(shift[128]) == pytest.approx(0.0, abs=1e-6), "nothing at mid grey"


def test_highlights_recovers_only_the_bright_end() -> None:
    wedge = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    image = np.repeat(wedge[:, np.newaxis], 3, axis=1)[np.newaxis, ...]

    shift = tone_region_shift(image, recipe(highlights=-100.0))[0]

    assert float(shift[0]) == pytest.approx(0.0, abs=1e-6)
    assert float(shift[:100].min()) == pytest.approx(0.0, abs=1e-6)
    assert float(shift[200]) < -0.1, "the bright end must come down"


def test_the_regional_shift_is_neutral_when_all_four_are_zero() -> None:
    shift = tone_region_shift(MID_GREY, recipe())

    assert float(shift[0, 0]) == 0.0


def test_the_shift_is_the_same_on_every_channel() -> None:
    """A shared shift changes brightness without dragging the hue with it."""
    coloured = np.array([[[0.10, 0.30, 0.55]]], dtype=np.float32)

    out = render(coloured, recipe(shadows=60.0))

    deltas = out[0, 0] - coloured[0, 0]
    assert float(deltas.max() - deltas.min()) == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------- 3.4 contrast


def test_contrast_leaves_mid_grey_where_it_is() -> None:
    """Intent: pull the ends apart around mid grey, which itself does not move."""
    for amount in (-100.0, -40.0, 40.0, 100.0):
        out = apply_contrast(np.float32(0.5), amount)
        assert float(out) == pytest.approx(0.5, abs=1e-6)


def test_positive_contrast_darkens_darks_and_brightens_brights() -> None:
    out = apply_contrast(np.array([0.25, 0.75], dtype=np.float32), 50.0)

    assert float(out[0]) < 0.25
    assert float(out[1]) > 0.75


def test_negative_contrast_does_the_opposite() -> None:
    out = apply_contrast(np.array([0.25, 0.75], dtype=np.float32), -50.0)

    assert float(out[0]) > 0.25
    assert float(out[1]) < 0.75


@pytest.mark.parametrize("amount", [-100.0, -50.0, 0.0, 50.0, 100.0])
def test_contrast_is_monotone_and_stays_in_range(amount: float) -> None:
    """Non-monotone contrast would invert a gradient; out of range would clip early."""
    x = np.linspace(0.0, 1.0, 2001, dtype=np.float32)
    out = apply_contrast(x, amount).astype(np.float64)

    assert np.all(np.diff(out) >= -1e-9)
    assert float(out.min()) >= -1e-6
    assert float(out.max()) <= 1.0 + 1e-6


def test_zero_contrast_is_exactly_the_identity() -> None:
    x = np.linspace(0.0, 1.0, 257, dtype=np.float32)

    assert np.array_equal(apply_contrast(x, 0.0), x)


# ------------------------------------------------- 3.6 saturation / vibrance


def test_full_negative_saturation_removes_all_colour() -> None:
    """Intent: saturation acts on every colour equally; -100 leaves grey."""
    coloured = np.array([[[0.8, 0.2, 0.4]]], dtype=np.float32)

    out = apply_saturation(coloured, recipe(saturation=-100.0))

    assert float(out.max() - out.min()) == pytest.approx(0.0, abs=1e-6)
    assert float(out[0, 0, 0]) == pytest.approx(float(luma(coloured)[0, 0]), abs=1e-6)


def test_saturation_leaves_a_grey_pixel_alone() -> None:
    for amount in (-100.0, -30.0, 30.0, 100.0):
        out = apply_saturation(MID_GREY, recipe(saturation=amount))
        assert out == pytest.approx(MID_GREY, abs=1e-6)


def test_vibrance_spares_what_is_already_saturated() -> None:
    """Intent: vibrance acts harder on pale colour than on vivid colour.

    This is the only behavioural difference between vibrance and saturation, and
    it is why the fixture set needs a saturation ramp — an image of grey and
    fully saturated hues cannot show it (notes §B5).
    """
    pale = np.array([[[0.60, 0.50, 0.45]]], dtype=np.float32)
    vivid = np.array([[[0.95, 0.05, 0.05]]], dtype=np.float32)

    def gain(pixel: np.ndarray) -> float:
        """How much vibrance widened the distance from grey, as a fraction."""
        out = apply_saturation(pixel, recipe(vibrance=80.0))
        before = float(pixel.max() - pixel.min())
        after = float(out.max() - out.min())
        return after / before - 1.0

    # Compared as a gain, not as an absolute shift: the vivid pixel starts much
    # further from grey, so measuring absolute movement would partly hide the
    # very selectivity being tested.
    assert gain(pale) > gain(vivid) * 5.0, "vibrance must favour the less saturated pixel"


def test_saturation_does_not_spare_anything() -> None:
    """The contrast to the test above: plain saturation treats both the same."""
    pale = np.array([[[0.60, 0.50, 0.45]]], dtype=np.float32)
    vivid = np.array([[[0.95, 0.05, 0.05]]], dtype=np.float32)

    def relative_change(pixel: np.ndarray) -> float:
        out = apply_saturation(pixel, recipe(saturation=50.0))
        spread_before = float(pixel.max() - pixel.min())
        spread_after = float(out.max() - out.min())
        return spread_after / spread_before

    assert relative_change(pale) == pytest.approx(relative_change(vivid), rel=1e-5)
