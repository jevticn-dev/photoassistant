"""Rules the renderer must obey for **every** recipe, not for chosen examples.

Every other test in this suite is example-based: for this input, expect this
output. That only ever checks the combinations someone thought to write down, and
three real defects survived 191 such tests because no test happened to move the
right four sliders at once. The cyan one was found by looking at a picture.

These are stated the other way round — a rule that must hold over the whole
parameter space — and ``hypothesis`` generates the inputs. When one fails it
shrinks the counterexample to the smallest recipe that still reproduces it, which
is the part that turns "something is wrong" into "``blacks`` and ``vibrance``
together, nothing else matters".

The catalogue, and what each rule is here to catch:

===  =============================================  =====================================
 #   Rule                                           Catches
===  =============================================  =====================================
 1   output stays in [0, 1]                         step 11 not clipping
 2   output is always a finite number               division by zero, root of a negative
 3   same input twice gives the same output         hidden state, randomness
 4   a neutral recipe is the identity, bit for bit   the skip rule (spec §4.1)
 5   grey stays grey without white balance          colour appearing from nowhere
 6   brighter in never comes out darker             a formula meeting a value it was not
                                                    written for (ADR-20)
 7   the colour stage never reorders the channels    gain below -1 mirroring the pixel
 8   the regional sliders' compression is bounded    the known mask characteristic
 9   colour amplification is bounded                 runaway saturation
===  =============================================  =====================================

Rule 8 is the one that is deliberately not strict, and it is worth reading the
note above it before changing anything there.

These run against the NumPy renderer only. That is not an oversight: the rules
are about whether the *formulas* are sane, and the golden test is what proves the
WebGL translation matches. Sane formulas plus proven agreement is what makes the
shader sane too — see ``docs/notes/phase-1-concepts.md`` §B16.
"""

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from photoassistant.renderer.pipeline import quantise, render
from photoassistant.schema import MIN_POINT_SPACING, EditRecipe

# Deterministic in CI: a suite that fails on one run in fifty and passes on the
# next teaches people to re-run it rather than to read it. `derandomize` fixes
# the generator, so a failure here is always reproducible. Exploration beyond
# this fixed set is what the sweep scripts in the phase report did once, by hand.
PROPERTY_SETTINGS = settings(
    max_examples=300,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

NORMALISED = st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False)
STOPS = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)
UNIT = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Region sliders held below the value at which a single slider starts to compress
# an end of the range. Used by the tighter form of rule 6 — see the note on
# rule 8 for what the two bounds mean and where they come from.
GENTLE_REGION = st.floats(min_value=-75.0, max_value=75.0, allow_nan=False, allow_infinity=False)

# The two bounds on brightness reversal, both measured rather than chosen, and
# both above the worst case seen so that ordinary noise cannot make the suite
# flaky. Spec §7.5 records how they were obtained.
#
#   gentle regions (±75)  → worst measured 5 over 6000 recipes
#   full range            → worst measured 5 over 6000 recipes
#
# **Both were far larger until ADR-22**: 47 and 78 respectively. The regional
# shift is now a monotone table (spec §3.3), so the four masks can no longer
# reverse the ordering however strong they are set, and the two ranges stop being
# meaningfully different. What is left is 8-bit rounding, which can put two
# neighbouring inputs on opposite sides of a boundary — measured as `129, 128` at
# input level 244.
#
# Both are measured with a **neutral** curve, and that is the point of the split
# rather than a convenience. The master curve may be arbitrarily steep within the
# schema — points 1/1023 apart may differ by a full unit in y, a slope of 1023 —
# and a steep segment multiplies any small wobble beneath it. A bound in 8-bit
# steps is therefore meaningless while the curve is free: hypothesis duly found
# a curve of slope 32 turning a 1-step rounding wobble into 36.
#
# The decomposition is what makes the split rigorous rather than convenient. A
# monotone function of a monotone function is monotone, so proving these two
# separately proves the whole:
#
#   * the pipeline without the curve  → bounded here
#   * the curve's table is monotone   → the rule below, over generated curves
#
# The limits sit above the measured worst rather than at it, so that ordinary
# rounding noise does not make the tests flaky. They are now more than twenty
# times below the defects ADR-20 repairs, which reversed by 118 and 255 steps.
GENTLE_COMPRESSION_LIMIT = 8
MEASURED_COMPRESSION_LIMIT = 8


@st.composite
def curves(draw: st.DrawFn) -> list[list[float]]:
    """A tone curve the schema would accept: spanning [0, 1], points far enough apart.

    The spacing filter is not decoration. Before ADR-20 the schema asked only for
    strictly increasing x, and this strategy duly produced two points a denormal
    apart — ``[(0.0, 0.0), (2.2e-309, 1.0), (1.0, 0.0)]`` — whose secant slope
    overflows and turns **every pixel of the image** into NaN. That is how the
    fourth defect was found. Generating invalid recipes now would only re-test the
    schema's rejection, which ``test_schema_roundtrip.py`` already covers.
    """
    count = draw(st.integers(min_value=0, max_value=4))
    candidates = sorted(draw(st.lists(UNIT, min_size=count, max_size=count)))

    xs = [0.0]
    for x in candidates:
        if x - xs[-1] >= MIN_POINT_SPACING and 1.0 - x >= MIN_POINT_SPACING:
            xs.append(x)
    xs.append(1.0)

    return [[x, draw(UNIT)] for x in xs]


@st.composite
def ascending_curves(draw: st.DrawFn) -> list[list[float]]:
    """A curve that does not itself reverse brightness.

    Needed because the master curve is the **one** operation allowed to map
    brightness arbitrarily: §3.5 says "arbitrary mapping of input brightness to
    output", and only x is constrained by §6.1 — y is free. So
    ``[(0, 1), (1, 0)]`` is a legitimate recipe, a negative, and it reverses the
    whole image on purpose.

    The property tests found exactly that curve and reported it as a defect. The
    rule was wrong, not the renderer: "brighter in, never darker out" holds for
    every operation **except** the one whose stated job is to be arbitrary. Rules
    6 and 8 therefore draw from here, and the curve path is still exercised —
    just with a curve that ascends.
    """
    points = draw(curves())
    ys = sorted(y for _, y in points)
    return [[x, y] for (x, _), y in zip(points, ys, strict=True)]


@st.composite
def recipes(
    draw: st.DrawFn,
    region: st.SearchStrategy[float] = NORMALISED,
    curve: st.SearchStrategy[list[list[float]]] | None = None,
) -> EditRecipe:
    return EditRecipe.model_validate(
        {
            "schema": 1,
            "white_balance": {"temperature": draw(NORMALISED), "tint": draw(NORMALISED)},
            "tone": {
                "exposure": draw(STOPS),
                "contrast": draw(NORMALISED),
                "highlights": draw(region),
                "shadows": draw(region),
                "whites": draw(region),
                "blacks": draw(region),
            },
            "color": {"saturation": draw(NORMALISED), "vibrance": draw(NORMALISED)},
            "tone_curve": {"points": draw(curve if curve is not None else curves())},
        }
    )


def grey_wedge() -> np.ndarray:
    """Every 8-bit grey level in order — the densest brightness input there is."""
    ramp = np.arange(256, dtype=np.float32) / np.float32(255.0)
    return np.repeat(ramp[:, np.newaxis], 3, axis=1)[np.newaxis, ...]


def colour_cube() -> np.ndarray:
    """A coarse grid over the whole RGB cube, so no corner of colour is missed."""
    levels = np.linspace(0.0, 1.0, 8, dtype=np.float32)
    grid = np.stack(np.meshgrid(levels, levels, levels, indexing="ij"), axis=-1)
    return grid.reshape(1, -1, 3).astype(np.float32)


WEDGE = grey_wedge()
CUBE = colour_cube()

NEUTRAL_CURVE = [[0.0, 0.0], [1.0, 1.0]]


def largest_reversal(image: np.ndarray, recipe: EditRecipe) -> int:
    """Biggest drop in output brightness as input brightness rises, in 8-bit steps.

    Zero means the ordering survived. Any positive value means two pixels came
    out in the opposite order to the one they went in, which no operation in the
    spec is allowed to do: the curve is monotone by §6.2, contrast by §3.4, and
    exposure and white balance are multiplications by a positive number.
    """
    out = quantise(render(image, recipe))[0].max(axis=-1).astype(np.int16)
    return int(np.max(np.maximum.accumulate(out) - out))


# ------------------------------------------------------------------ 1, 2, 3


@given(recipe=recipes())
@PROPERTY_SETTINGS
def test_the_output_never_leaves_the_range(recipe: EditRecipe) -> None:
    """Step 11 clips exactly once, so nothing can escape whatever the recipe."""
    out = render(CUBE, recipe)

    assert float(out.min()) >= 0.0
    assert float(out.max()) <= 1.0


@given(recipe=recipes())
@PROPERTY_SETTINGS
def test_the_output_is_always_a_real_number(recipe: EditRecipe) -> None:
    """No NaN, no infinity — a division by zero or a root of a negative would show here."""
    assert np.all(np.isfinite(render(CUBE, recipe)))


@given(recipe=recipes())
@PROPERTY_SETTINGS
def test_rendering_twice_gives_the_same_answer(recipe: EditRecipe) -> None:
    """Determinism (spec §1): no clock, no randomness, no state carried between calls."""
    assert np.array_equal(render(CUBE, recipe), render(CUBE, recipe))


# ----------------------------------------------------------------------- 4


@given(
    image=st.lists(
        st.tuples(UNIT, UNIT, UNIT), min_size=1, max_size=64
    ).map(lambda rows: np.array([rows], dtype=np.float32))
)
@PROPERTY_SETTINGS
def test_a_neutral_recipe_is_the_identity_for_any_image(image: np.ndarray) -> None:
    """Bit-exact, for every image and not only the fixtures (spec §4.1, §8.5).

    Holds because a neutral recipe performs no arithmetic at all. A failure means
    the skip logic, not precision.
    """
    assert np.array_equal(render(image, EditRecipe()), image)


# ----------------------------------------------------------------------- 5


@given(recipe=recipes())
@PROPERTY_SETTINGS
def test_grey_stays_grey_when_white_balance_is_neutral(recipe: EditRecipe) -> None:
    """White balance is the only operation allowed to introduce colour.

    Everything else either adds the same amount to all three channels or scales
    their distance from a shared value, so a pixel that arrives neutral must
    leave neutral.
    """
    neutral_white_balance = recipe.model_copy(
        update={"white_balance": EditRecipe().white_balance}
    )

    out = quantise(render(WEDGE, neutral_white_balance))[0].astype(np.int16)

    assert int((out.max(axis=-1) - out.min(axis=-1)).max()) == 0


# ----------------------------------------------------------------------- 6


@given(recipe=recipes(region=GENTLE_REGION, curve=st.just(NEUTRAL_CURVE)))
@PROPERTY_SETTINGS
def test_a_brighter_pixel_never_comes_out_darker(recipe: EditRecipe) -> None:
    """The rule that caught ADR-20, and the most valuable one here.

    Every operation in the spec is monotone in brightness by construction, so a
    reversal cannot be a matter of taste — it means a formula met a value it was
    not written for. Both defects behind ADR-20 announce themselves here, and
    loudly: exposure with contrast reverses by the full range, turning white into
    black.

    The region sliders are drawn from a narrower interval than the schema allows,
    for the reason set out on the next test. Every defect ADR-20 repairs occurs
    well inside that interval, so nothing is being hidden by the restriction.

    The allowance covers one effect that is not a defect: rounding a continuous
    result to 256 levels can put two neighbouring inputs on opposite sides of a
    boundary — measured as ``129, 128`` at input level 244.

    Until ADR-22 it also had to cover the region masks, which compressed an end of
    the range once several sliders combined. That is gone: the regional shift is a
    monotone table now, and the measured worst fell from 47 to 5.

    Kept far below the defects this rule exists for, which reverse by 118 and 255
    steps out of 255.
    """
    assert largest_reversal(WEDGE, recipe) <= GENTLE_COMPRESSION_LIMIT


# ----------------------------------------------------------------------- 7


@given(recipe=recipes(curve=ascending_curves()))
@PROPERTY_SETTINGS
def test_the_channels_never_change_places(recipe: EditRecipe) -> None:
    """If red was the strongest channel, it must not come out the weakest.

    Two operations are excluded, both because reordering is legitimately theirs.
    White balance moves the channels against each other by definition. And a
    descending master curve is a photographic negative: the same table is applied
    to all three channels, so the strongest becomes the weakest, on purpose. The
    property tests reported that curve as a defect before this restriction, and
    the rule was wrong rather than the renderer.

    What remains is everything that changes brightness or distance from grey, and
    none of that may reorder the channels — that is a hue flip, and a desaturating
    control that inverts a colour instead of removing it is not doing what §3.6
    says it does.
    """
    neutral_white_balance = recipe.model_copy(
        update={"white_balance": EditRecipe().white_balance}
    )

    before = quantise(CUBE)[0].astype(np.int16)
    after = quantise(render(CUBE, neutral_white_balance))[0].astype(np.int16)

    # Compare only pixels whose channels were clearly ordered to begin with:
    # a near-tie can swap on rounding alone and says nothing about the formulas.
    clear = (before.max(axis=-1) - before.min(axis=-1)) > 8
    before, after = before[clear], after[clear]

    strongest = before.argmax(axis=-1)[:, np.newaxis]
    value_after = np.take_along_axis(after, strongest, axis=-1)[:, 0]

    # Strictly below **every** other channel is the flip. A tie is not: a flat
    # curve maps the whole image to one value, where no channel leads and none
    # trails, and reading argmin there would invent an ordering that is not
    # present. The property tests found that too, reported as a defect that was
    # not one.
    others = after.copy()
    np.put_along_axis(others, strongest, np.iinfo(np.int16).max, axis=-1)

    assert not np.any(value_after < others.min(axis=-1)), (
        "a channel went from strongest to weakest"
    )


# ----------------------------------------------------------------------- 8


# The one rule stated as a bound rather than an absolute, and the reason is
# recorded rather than assumed. Spec §7.5 carries the full account; the short
# version is here because this is where the number is enforced.
#
# Each of the four tone-region masks has at least one edge 0.25 wide. Over that
# edge a strong slider pushes down faster than brightness rises, so a gradient
# reverses locally — a visible band in a sky. The total shift is the **sum** of
# four masked contributions, so their slopes add: `tint`, `highlights` and
# `whites`, each on its own below ±75, together produce a 30-step reversal. A
# per-slider threshold does not describe this, which is why the bound is stated
# over the whole space instead.
#
# Measured over the parameter ranges the phase 1b probe actually fitted: median
# and 90th percentile 0, 99th percentile 24, worst 60, and 2.1% of recipes above
# 12 steps.
#
# This is not the ADR-20 family: no value leaves [0, 1]. It follows from K_REG
# and the mask widths, both choices (spec §10), and weakening K_REG does not fix
# it at an acceptable price — the band only disappears at 0.125, which costs half
# the reach of all four sliders, while `whites` and `blacks` already sit pinned at
# their limits on 5% and 3% of images. That is the shortage ADR-19 had to undo for
# white balance.
#
# So it is bounded here and decided in phase 2, where fitting ~1000 edits yields
# the joint distribution of fitted regional values as a by-product. ADR-20,
# decision B.


@given(recipe=recipes(curve=st.just(NEUTRAL_CURVE)))
@PROPERTY_SETTINGS
def test_regional_compression_stays_within_the_measured_bound(recipe: EditRecipe) -> None:
    """The region masks compress an end of the range. Bounded, not absent.

    The bound is above the worst case measured (60) rather than at it, so that
    ordinary noise does not turn this into a flaky test. It is still an order of
    magnitude below the defects ADR-20 repairs, which reversed by 118 and 255
    steps, so it keeps its power as a regression guard.
    """
    assert largest_reversal(WEDGE, recipe) <= MEASURED_COMPRESSION_LIMIT


# ----------------------------------------------------------------------- 9


@given(
    saturation=NORMALISED,
    vibrance=NORMALISED,
)
@PROPERTY_SETTINGS
def test_colour_is_amplified_but_never_invented(saturation: float, vibrance: float) -> None:
    """A pixel's distance from grey may grow, by a bounded factor, and may not flip sign.

    The bound is the largest gain the schema allows: saturation and vibrance both
    at +100 give a factor of 3. Anything beyond that means the gain itself has
    escaped its range.
    """
    recipe = EditRecipe.model_validate(
        {"schema": 1, "color": {"saturation": saturation, "vibrance": vibrance}}
    )

    before = CUBE
    after = render(before, recipe)

    grey_before = before.mean(axis=-1, keepdims=True)
    grey_after = after.mean(axis=-1, keepdims=True)
    spread_before = float(np.abs(before - grey_before).max())
    spread_after = float(np.abs(after - grey_after).max())

    assert spread_after <= 3.0 * spread_before + 1e-6


@pytest.mark.parametrize("amount", [-100.0, -50.0, 0.0, 50.0, 100.0])
def test_a_neutral_pixel_is_untouched_by_the_colour_stage(amount: float) -> None:
    """The boundary case of rule 9: no distance from grey, so nothing to scale."""
    grey = np.full((1, 1, 3), 0.42, dtype=np.float32)

    for key in ("saturation", "vibrance"):
        recipe = EditRecipe.model_validate({"schema": 1, "color": {key: amount}})
        assert render(grey, recipe) == pytest.approx(grey, abs=1e-6)


# ---------------------------------------------------------------------- 10


@given(points=ascending_curves())
@PROPERTY_SETTINGS
def test_the_curve_table_is_monotone_for_any_ascending_curve(
    points: list[list[float]],
) -> None:
    """The second half of the decomposition above.

    Rules 6 and 8 hold the curve neutral, because a steep curve multiplies any
    wobble beneath it and makes a bound in 8-bit steps meaningless. That is only
    legitimate if the curve itself cannot introduce a reversal — which is what
    Fritsch-Carlson is for (§6.2) and what this asserts over generated curves
    rather than the three fixed ones in ``test_renderer_curve.py``.

    With both halves proven, the whole pipeline is monotone: a monotone function
    of a monotone function is monotone.
    """
    from photoassistant.renderer.curve import build_lut

    lut = build_lut(np.asarray(points, dtype=np.float64)).astype(np.float64)

    assert np.all(np.isfinite(lut))
    assert np.all(np.diff(lut) >= -1e-9), "the interpolated table dips"
