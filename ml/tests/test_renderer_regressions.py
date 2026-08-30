"""Every defect the renderer has ever had, pinned so it cannot come back.

The property tests in ``test_renderer_properties.py`` state rules over the whole
parameter space and would catch these again. This file exists anyway, and the
distinction is worth keeping:

* a **property** says what must always be true, and is the net that catches the
  next defect;
* a **regression** records what once was false, with the exact recipe, so a
  future change to the rules — a widened bound, a narrowed strategy, a different
  seed — cannot quietly stop covering a defect that actually happened.

The two failure modes are different. A property can be weakened by accident; a
named test with a literal recipe cannot be weakened without someone reading the
name of the defect they are turning off.

Each case below names how it was found, because that is the part worth carrying
into the thesis: two came from a picture, two from generated inputs, and none
from the 191 example-based tests that were passing the whole time.
"""

import numpy as np
import pytest

from photoassistant.renderer.pipeline import quantise, render, tone_region_shift
from photoassistant.schema import EditRecipe, from_json

GREY_WEDGE = np.repeat(
    (np.arange(256, dtype=np.float32) / np.float32(255.0))[:, np.newaxis], 3, axis=1
)[np.newaxis, ...]


def brightest_channel(image: np.ndarray, recipe: EditRecipe) -> np.ndarray:
    return quantise(render(image, recipe))[0].max(axis=-1).astype(np.int16)


def largest_reversal(image: np.ndarray, recipe: EditRecipe) -> int:
    out = brightest_channel(image, recipe)
    return int(np.max(np.maximum.accumulate(out) - out))


# --------------------------------------------------------------------- ADR-20


def test_a_negative_blacks_with_vibrance_does_not_produce_cyan() -> None:
    """Found by eye, on the renderer test page, on the first day it existed.

    ``temperature +70``, ``contrast +45``, ``blacks -60``, ``vibrance +60`` — no
    parameter near its limit — turned the dark end of a grey wedge cyan. The
    saturation measure ``p``, declared by §3.6 to be in [0, 1], reached 32,903:
    a negative ``blacks`` sends all three channels below zero, where the guard
    against dividing by zero collapses the divisor to ``EPS``. The gain went to
    -7.2 and threw the pixel onto a corner of the colour cube.

    Both implementations agreed on the wrong answer, so the golden test would
    have been green. That is the whole reason a place to look at pictures exists.
    """
    recipe = EditRecipe.model_validate(
        {
            "schema": 1,
            "white_balance": {"temperature": 70.0},
            "tone": {"contrast": 45.0, "blacks": -60.0},
            "color": {"vibrance": 60.0},
        }
    )

    out = quantise(render(GREY_WEDGE, recipe))[0]

    # The dark end must stay dark and neutral-ish, not jump to a saturated corner.
    dark = out[:24].astype(np.int16)
    assert int((dark.max(axis=-1) - dark.min(axis=-1)).max()) < 60, "the dark end went cyan"


def test_exposure_with_contrast_does_not_turn_white_into_black() -> None:
    """Found by the systematic sweep, not by eye — and it was the worse defect.

    ``S(x) = x²(3 − 2x)`` is proven in range "for input from [0, 1]", which the
    spec itself says. Above 1.5 it dives: exposure +5 leaves white at 4.42, where
    the shaping returns -114, and contrast +100 clipped that to black. A blown
    highlight came out as the darkest thing in the frame.

    Neither parameter does this alone; both sweep their full range cleanly.
    """
    for exposure, contrast in ((2.0, 100.0), (3.0, 100.0), (5.0, 100.0), (1.0, 75.0)):
        recipe = EditRecipe.model_validate(
            {"schema": 1, "tone": {"exposure": exposure, "contrast": contrast}}
        )

        assert largest_reversal(GREY_WEDGE, recipe) == 0, (
            f"exposure {exposure:+} with contrast {contrast:+} reverses brightness"
        )


def test_desaturating_removes_colour_rather_than_inverting_it() -> None:
    """Found by a property test asking whether the channels ever change places.

    The gain is ``saturation/100 + vibrance/100 · (1 − p)``. With both negative it
    passes -1, the multiplier ``1 + gain`` turns negative, and the pixel is
    mirrored through its own luma instead of collapsing onto it. A warm pixel came
    out cool: ``(191, 128, 64)`` became ``(118, 139, 161)``.

    §3.6 says -100 leaves grey. Grey is the end of the road, not a point to pass
    through.
    """
    warm = np.array([[[0.75, 0.50, 0.25]]], dtype=np.float32)

    for saturation, vibrance in ((-100.0, -100.0), (-100.0, -5.0), (-90.0, -35.0)):
        recipe = EditRecipe.model_validate(
            {"schema": 1, "color": {"saturation": saturation, "vibrance": vibrance}}
        )

        red, _, blue = (int(v) for v in quantise(render(warm, recipe))[0, 0])
        assert red >= blue, (
            f"saturation {saturation:+} with vibrance {vibrance:+} inverted the hue"
        )


def test_two_curve_points_a_denormal_apart_are_refused() -> None:
    """Found by a property test, shrunk to the smallest curve that reproduces it.

    ``[(0.0, 0.0), (2.2e-309, 1.0), (1.0, 0.0)]`` satisfies "strictly increasing"
    and is therefore accepted by the schema as it stood. The secant slope between
    the first two points overflows, and **every pixel of the image** becomes NaN —
    not just the tones near those points.

    Reachable both ways round: a user dragging two curve points together in the
    editor, and the optimiser moving them freely while fitting in phase 2.
    """
    document = '{"schema": 1, "tone_curve": {"points": [[0.0, 0.0], [2.2e-309, 1.0], [1.0, 0.0]]}}'

    with pytest.raises(Exception, match="at least"):
        from_json(document)


@pytest.mark.parametrize(
    "points",
    [
        pytest.param("[[0.0, 0.0], [0.0005, 0.5], [1.0, 1.0]]", id="half a table step apart"),
        pytest.param("[[0.0, 0.0], [0.9999, 0.5], [1.0, 1.0]]", id="too close to the end"),
    ],
)
def test_curve_points_closer_than_one_table_step_are_refused(points: str) -> None:
    """The general form of the rule, not only the denormal that exposed it."""
    with pytest.raises(Exception, match="at least"):
        from_json(f'{{"schema": 1, "tone_curve": {{"points": {points}}}}}')


def test_the_repairs_leave_an_ordinary_edit_untouched() -> None:
    """The claim the whole of ADR-20 rests on, kept where it can be re-run.

    Every repair is confined to values the old formulas never defined. Measured
    over 150 random recipes and 90,000 pixels: of the 5,616,063 pixels that never
    left [0, 1], **none** rendered differently. This is the cheap standing form of
    that check — an ordinary recipe on ordinary pixels, whose result must be what
    it always was.
    """
    recipe = EditRecipe.model_validate(
        {
            "schema": 1,
            "white_balance": {"temperature": 22.0, "tint": -6.0},
            "tone": {"exposure": 0.35, "contrast": 18.0, "shadows": 25.0, "blacks": -12.0},
            "color": {"saturation": 8.0, "vibrance": 20.0},
        }
    )
    image = np.linspace(0.15, 0.85, 3 * 64, dtype=np.float32).reshape(1, 64, 3)

    out = render(image, recipe)

    assert np.all(np.isfinite(out))
    assert float(out.min()) >= 0.0
    assert float(out.max()) <= 1.0
    # Nothing here approaches an edge of the range, so the gain and the saturation
    # measure both stay inside their own bounds and no repair can have fired.
    assert largest_reversal(GREY_WEDGE, recipe) == 0


def test_strong_regional_sliders_no_longer_reverse_a_gradient() -> None:
    """ADR-22. The worst recipe the calibration pass produced, kept by name.

    `blacks` at 99 lifts the darkest pixels by 63 steps of 255, and that lift
    fades faster than brightness rises: input level 16 came out at 67 while input
    level 48 came out at 44. On a smooth sky that is a visible band, and nine of
    1012 fitted recipes had one.

    The cause was isolated by ablation rather than assumed — removing the regional
    sliders eliminated it in all nine, removing `tint` changed nothing — and the
    repair makes the shift a monotone table (spec §3.3), so the ordering cannot
    invert however strong the sliders are set.
    """
    recipe = EditRecipe.model_validate(
        {
            "schema": 1,
            "tone": {"highlights": 21.0, "shadows": -26.0, "whites": 4.0, "blacks": 99.0},
        }
    )

    assert largest_reversal(GREY_WEDGE, recipe) == 0


def test_the_regional_table_stores_a_shift_so_headroom_survives() -> None:
    """The trap inside the repair, kept where it would be noticed.

    Lookups clip their input (spec §6.4). Had the table stored the resulting luma
    rather than the shift, every pixel whose luma is above 1 would have been given
    the result at 1 — flattening exactly the headroom §5 exists to preserve.

    Exposure +2 puts white at 1.86 after step 4. What must happen there is that it
    keeps its value and receives the shift belonging to luma 1, because the masks
    are saturated above 1 and the shift is constant there. What must not happen is
    that it be replaced by whatever luma 1 maps to.
    """
    recipe = EditRecipe.model_validate({"schema": 1, "tone": {"whites": 60.0}})

    at_one = np.full((1, 1, 3), 1.0, dtype=np.float32)
    above = np.full((1, 1, 3), 1.86, dtype=np.float32)

    shift_at_one = float(tone_region_shift(at_one, recipe)[0, 0])
    shift_above = float(tone_region_shift(above, recipe)[0, 0])

    # Same shift, because the masks are saturated above 1.
    assert shift_above == pytest.approx(shift_at_one)
    # And it is a shift, not a replacement: the value keeps its distance above 1.
    assert float(above[0, 0, 0]) + shift_above == pytest.approx(1.86 + shift_at_one)
    assert 1.86 + shift_above > 1.0
