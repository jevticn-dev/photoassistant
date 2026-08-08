"""The whole pipeline: order, the skip rule, clipping and quantisation.

The identity assertion is the load-bearing one. Everything else here checks that
an operation happens where the spec says it happens.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photoassistant.renderer.pipeline import quantise, render
from photoassistant.schema import EditRecipe, load

FIXTURE_EDITS = Path(__file__).parents[2] / "fixtures" / "edits"
FIXTURE_IMAGES = Path(__file__).parents[2] / "fixtures" / "images"

RECIPES = ["curve_only", "extreme", "neutral", "warm_bright"]
IMAGES = ["clipping_patches", "gray_wedge", "hue_sweep", "noise_block", "saturation_ramp"]


def read_image(name: str) -> np.ndarray:
    with Image.open(FIXTURE_IMAGES / f"{name}.png") as handle:
        return np.asarray(handle.convert("RGB"), dtype=np.float32) / np.float32(255.0)


@pytest.mark.parametrize("image_name", IMAGES)
def test_a_neutral_recipe_returns_the_image_untouched(image_name: str) -> None:
    """Bit-exact, not approximately equal — spec §4.1 and §8.5.

    This holds because a neutral recipe performs **no arithmetic at all**: every
    operation is skipped, and steps 1 and 4 are skipped together with white
    balance and exposure. Decode followed by encode is not an exact inverse in
    finite precision, so running that pair without cause would break equality
    here and nowhere else. A failure means the skip logic, not precision.
    """
    image = read_image(image_name)

    out = render(image, EditRecipe())

    assert np.array_equal(out, image)


@pytest.mark.parametrize("image_name", IMAGES)
@pytest.mark.parametrize("recipe_name", RECIPES)
def test_every_fixture_combination_renders_in_range(recipe_name: str, image_name: str) -> None:
    """Step 11 clips exactly once, so nothing can leave [0, 1] whatever the recipe."""
    out = render(read_image(image_name), load(FIXTURE_EDITS / f"{recipe_name}.json"))

    assert out.dtype == np.float32
    assert float(out.min()) >= 0.0
    assert float(out.max()) <= 1.0
    assert np.all(np.isfinite(out))


@pytest.mark.parametrize("recipe_name", ["warm_bright", "extreme", "curve_only"])
def test_a_non_neutral_recipe_changes_something(recipe_name: str) -> None:
    """Guards the tests above: a renderer that did nothing would pass all of them."""
    image = read_image("gray_wedge")

    out = render(image, load(FIXTURE_EDITS / f"{recipe_name}.json"))

    assert not np.array_equal(out, image)


def test_the_shape_and_type_survive() -> None:
    image = read_image("saturation_ramp")

    out = render(image, load(FIXTURE_EDITS / "warm_bright.json"))

    assert out.shape == image.shape
    assert out.dtype == np.float32


def test_headroom_above_white_survives_to_step_11() -> None:
    """Why nothing is clipped before step 11 (spec §5).

    Exposure can take a value above 1 in linear space. If step 4 clipped, the
    headroom would be gone and no later operation could bring the value back.
    Rendering with and without a recovery parameter proves it survived.

    Which parameter does the recovering is not the obvious one — see the test
    below.
    """
    image = np.full((1, 1, 3), 0.6, dtype=np.float32)

    lifted = render(image, EditRecipe.model_validate({"schema": 1, "tone": {"exposure": 2.0}}))
    recovered = render(
        image,
        EditRecipe.model_validate({"schema": 1, "tone": {"exposure": 2.0, "whites": -100.0}}),
    )

    assert float(lifted[0, 0, 0]) == pytest.approx(1.0, abs=1e-6), "exposure alone clips to white"
    assert float(recovered[0, 0, 0]) < 0.95, "the value above white was still there to pull back"


def test_above_white_only_whites_reaches_the_pixel_not_highlights() -> None:
    """A consequence of the mask definitions that the spec does not state outright.

    ``smoothstep`` clamps, so at a luma above 1 the highlights window has already
    closed (weight 0) and whites is fully open (weight 1). A pixel blown past
    white is therefore reachable by ``whites`` alone.

    Defensible — whites owns the extreme end of the range by design — but worth
    pinning, because it is the opposite of the habit most editors teach, where
    Highlights is the recovery slider. It also constrains phase 2: an expert edit
    that recovered blown highlights can only be fitted through ``whites`` or the
    master curve. See ``docs/notes/phase-1-concepts.md`` §B3.
    """
    image = np.full((1, 1, 3), 0.6, dtype=np.float32)
    blown = {"schema": 1, "tone": {"exposure": 2.0}}

    with_highlights = render(
        image, EditRecipe.model_validate({**blown, "tone": {**blown["tone"], "highlights": -100.0}})
    )
    with_whites = render(
        image, EditRecipe.model_validate({**blown, "tone": {**blown["tone"], "whites": -100.0}})
    )

    unreachable = float(with_highlights[0, 0, 0])
    assert unreachable == pytest.approx(1.0, abs=1e-6), "highlights cannot reach a blown pixel"
    assert float(with_whites[0, 0, 0]) < 0.95, "whites can"


def test_the_curve_is_applied_to_all_three_channels_alike() -> None:
    """A shared LUT keeps neutral grey neutral: the curve moves tone, not colour."""
    grey = np.full((1, 8, 3), 0.0, dtype=np.float32)
    grey[0, :, :] = np.linspace(0.1, 0.9, 8, dtype=np.float32)[:, np.newaxis]

    out = render(grey, load(FIXTURE_EDITS / "curve_only.json"))

    assert float(np.abs(out[..., 0] - out[..., 1]).max()) == pytest.approx(0.0, abs=1e-6)
    assert float(np.abs(out[..., 1] - out[..., 2]).max()) == pytest.approx(0.0, abs=1e-6)


def test_curve_only_moves_nothing_but_the_curve() -> None:
    """The fixture isolates the LUT path, so its effect must match the LUT alone."""
    from photoassistant.renderer.curve import apply_lut, build_lut

    image = read_image("gray_wedge")
    recipe = load(FIXTURE_EDITS / "curve_only.json")

    through_pipeline = render(image, recipe)
    through_lut = apply_lut(build_lut(np.asarray(recipe.tone_curve.points)), image)

    assert np.array_equal(through_pipeline, np.clip(through_lut, 0.0, 1.0))


def test_quantisation_follows_the_shared_rounding_rule() -> None:
    """floor(x * 255 + 0.5) — the rule the WebGL side's framebuffer already applies."""
    values = np.array([0.0, 0.5 / 255, 1.0 / 255, 0.5, 254.4 / 255, 1.0], dtype=np.float32)

    out = quantise(values)

    assert out.dtype == np.uint8
    assert out.tolist() == [0, 1, 1, 128, 254, 255]


def test_quantisation_clips_before_rounding() -> None:
    out = quantise(np.array([-0.4, 1.7], dtype=np.float32))

    assert out.tolist() == [0, 255]


@pytest.mark.parametrize("image_name", IMAGES)
def test_a_neutral_recipe_survives_quantisation_too(image_name: str) -> None:
    """The end-to-end form of the identity claim, in the 8-bit space the golden test compares."""
    with Image.open(FIXTURE_IMAGES / f"{image_name}.png") as handle:
        original = np.asarray(handle.convert("RGB"), dtype=np.uint8)

    out = quantise(render(original.astype(np.float32) / np.float32(255.0), EditRecipe()))

    assert np.array_equal(out, original)
