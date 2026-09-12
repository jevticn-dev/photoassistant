"""Translating PV2010 settings into edit schema v1.

The settings blocks here are **written by hand** in the catalogue's format rather
than copied out of it. The repository is public and the dataset licence is
research-only, so catalogue content does not go in — the same reason the renderer
fixtures are synthetic images (`docs/phases/phase-2.md`).
"""

import pytest

from pipeline.fivek.mapping import AUTO_SENTINEL, MEDIUM_CONTRAST, number, translate

NEUTRAL_BASELINE = {"Temperature": "5500", "Tint": "0"}


def settings(**overrides: object) -> dict[str, str]:
    """A minimal core-key block, which the catalogue guarantees is always present."""
    base = {
        "Exposure": "0",
        "Brightness": "0",
        "Contrast": "0",
        "Shadows": "0",
        "Temperature": "5500",
        "Tint": "0",
        "ToneCurveName": '"Linear"',
    }
    base.update({key: str(value) for key, value in overrides.items()})
    return base


def test_shadows_becomes_blacks_with_the_sign_inverted():
    """The trap the whole mapping exists to avoid.

    In PV2010 `Shadows` is the black point — today's "Blacks". Raising it deepens
    the blacks, which is our negative direction. Mapping by name would invert the
    most-used parameter in the catalogue and nothing would look obviously wrong.
    """
    recipe = translate(settings(Shadows=25), NEUTRAL_BASELINE)

    assert recipe.tone.blacks == -25
    assert recipe.tone.shadows == 0


def test_fill_light_becomes_shadows_not_shadows_itself():
    """The other half of the same trap: FillLight is the ancestor of today's Shadows."""
    recipe = translate(settings(FillLight=30), NEUTRAL_BASELINE)

    assert recipe.tone.shadows == 30
    assert recipe.tone.blacks == 0


def test_highlight_recovery_maps_to_the_negative_direction():
    recipe = translate(settings(HighlightRecovery=40), NEUTRAL_BASELINE)

    assert recipe.tone.highlights == -40


def test_an_absent_optional_key_means_neutral_not_missing():
    """Zero is never serialised, so absence carries information (`edit_schema` §6).

    Treating it as missing data would reject most of the catalogue.
    """
    recipe = translate(settings(), NEUTRAL_BASELINE)

    assert recipe.tone.shadows == 0
    assert recipe.color.vibrance == 0
    assert recipe.tone.highlights == 0


def test_the_auto_sentinel_is_ignored_rather_than_used_as_a_value():
    """Auto renditions carry -999999. Those collections are not read, but a number
    that size reaching a formula would be silent nonsense rather than an error."""
    assert number({"Exposure": str(AUTO_SENTINEL)}, "Exposure") == 0.0
    assert number({"Exposure": "-1000000"}, "Exposure") == 0.0


def test_contrast_rescales_its_two_halves_differently():
    """PV2010 contrast runs [-50, +100] onto our symmetric [-100, +100]."""
    assert translate(settings(Contrast=100), NEUTRAL_BASELINE).tone.contrast == 100
    assert translate(settings(Contrast=-50), NEUTRAL_BASELINE).tone.contrast == -100
    assert translate(settings(Contrast=50), NEUTRAL_BASELINE).tone.contrast == 50


def test_white_balance_is_a_shift_from_as_shot_not_an_absolute():
    """Temperature is absolute Kelvin, so the same value means different edits.

    An expert who left the camera's white balance alone applied no shift, however
    unusual that camera value was.
    """
    unchanged = translate(settings(Temperature=3000), {"Temperature": "3000", "Tint": "0"})

    assert unchanged.white_balance.temperature == 0


def test_warming_the_image_is_the_positive_direction():
    """Raising Kelvin warms the rendering, and our positive direction is warm."""
    warmed = translate(settings(Temperature=7000), NEUTRAL_BASELINE)

    assert warmed.white_balance.temperature > 0


def test_the_same_kelvin_step_counts_for_more_in_warm_light():
    """Mired, not Kelvin.

    500 K is a large change at 3000 K and a small one at 8000 K. Working in
    Kelvin directly would treat them as equal and get both wrong.
    """
    warm = translate(settings(Temperature=3500), {"Temperature": "3000", "Tint": "0"})
    cool = translate(settings(Temperature=8500), {"Temperature": "8000", "Tint": "0"})

    assert abs(warm.white_balance.temperature) > abs(cool.white_balance.temperature)


def test_the_named_medium_contrast_curve_is_reproduced_exactly():
    """12,4% of the catalogue uses it, so it is not an edge case."""
    recipe = translate(settings(ToneCurveName='"Medium Contrast"'), NEUTRAL_BASELINE)

    assert [tuple(point) for point in recipe.tone_curve.points] == MEDIUM_CONTRAST


def test_brightness_becomes_a_midtone_lift_because_it_has_no_equivalent():
    """The most approximate mapping of the set, and the one worth stating plainly."""
    lifted = translate(settings(Brightness=50), NEUTRAL_BASELINE)
    points = [tuple(point) for point in lifted.tone_curve.points]
    midtone = next(y for x, y in points if x == 0.5)

    assert midtone > 0.5
    # The endpoints are never moved: a curve that does not pass through the
    # corners changes black and white, which brightness does not do.
    assert points[0] == (0.0, 0.0)
    assert points[-1] == (1.0, 1.0)


def test_whites_has_no_source_and_stays_neutral():
    """PV2010 has no white-point control at all (`edit_schema` §3); the fit finds it."""
    assert translate(settings(Exposure=1, Shadows=20), NEUTRAL_BASELINE).tone.whites == 0


@pytest.mark.parametrize("value", [500, -500, 1e6])
def test_every_parameter_stays_inside_the_schema_range(value):
    """A translation that produced an out-of-range value would fail validation
    somewhere far from here, or worse, be clipped by whatever read it next."""
    recipe = translate(
        settings(Contrast=value, Shadows=value, Saturation=value, Vibrance=value),
        NEUTRAL_BASELINE,
    )

    assert -100 <= recipe.tone.contrast <= 100
    assert -100 <= recipe.tone.blacks <= 100
    assert -100 <= recipe.color.saturation <= 100
    assert -5 <= recipe.tone.exposure <= 5
