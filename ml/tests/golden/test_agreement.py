"""The golden test: do the two renderers agree?

This is the claim the whole two-implementation design rests on. The same image
and the same recipe, once through NumPy and once through the WebGL2 shader, must
land within the threshold of `RENDERER_SPEC.md` §8.5 — mean ΔE below 1, worst
pixel below 3.

**Two steps, because ΔE exists exactly once.** The browser renders the
combinations and writes PNGs (`npm --prefix frontend run golden`); this reads
them, renders the same combinations with NumPy, and measures. ΔE is symmetric, so
which side is "reference" makes no difference to the number — the only
consequence of the split is that the ruler lives in one place instead of two. Two
implementations of CIEDE2000 could disagree with each other, and a failure would
then have three possible causes instead of two (`notes` §B11).

**What this proves and what it does not.** It proves the two implementations
agree, not that either is correct — both could translate the specification
faithfully and both be wrong about what we wanted, and this would stay green.
That is not hypothetical: every defect ADR-20 repaired was of exactly that shape.
Correctness is the job of the per-operation tests, the property tests, and human
review of the spec before any code.

Skipped, loudly, when the browser output is absent — running the shader needs a
browser, and `pytest ml/tests` must stay usable without one. CI runs the render
step first, so a skip there is impossible.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photoassistant.renderer.color import delta_e
from photoassistant.renderer.curve import build_lut
from photoassistant.renderer.pipeline import quantise, render
from photoassistant.schema import EditRecipe

RENDERED = Path(__file__).parent / "rendered"
MANIFEST = RENDERED / "manifest.json"
IMAGES = Path(__file__).parents[3] / "fixtures" / "images"
CORPUS = Path(__file__).parents[3] / "fixtures" / "golden" / "recipes.json"

# Spec §8.5. The mean is what says the two agree in general; the maximum is what
# stops a handful of catastrophic pixels from hiding inside a good average — the
# failure mode phase 1b had to learn twice (`notes` §B10).
MEAN_THRESHOLD = 1.0
WORST_THRESHOLD = 3.0

pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(),
    reason=(
        "no browser output: run `npm --prefix frontend run golden` first. "
        "Agreement between the two renderers is unproven until it has been run."
    ),
)


def _corpus() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))["recipes"]


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


RECIPES = _corpus() if CORPUS.exists() else []
IMAGE_NAMES = sorted(path.stem for path in IMAGES.glob("*.png")) if IMAGES.exists() else []


def read_source(name: str) -> np.ndarray:
    with Image.open(IMAGES / f"{name}.png") as handle:
        return np.asarray(handle.convert("RGB"), dtype=np.float32) / np.float32(255.0)


def read_rendered(image: str, recipe: str) -> np.ndarray:
    with Image.open(RENDERED / f"{image}__{recipe}.png") as handle:
        return np.asarray(handle.convert("RGB"), dtype=np.uint8)


def test_the_browser_rendered_every_combination() -> None:
    """Guards every test below: a missing file would otherwise look like a pass."""
    manifest = _manifest()
    expected = len(IMAGE_NAMES) * len(RECIPES)

    assert manifest["combinations"] == expected, "the browser skipped some combinations"
    assert sorted(manifest["images"]) == IMAGE_NAMES
    assert manifest["recipes"] == [entry["name"] for entry in RECIPES]

    missing = [
        f"{image}__{entry['name']}.png"
        for image in IMAGE_NAMES
        for entry in RECIPES
        if not (RENDERED / f"{image}__{entry['name']}.png").exists()
    ]
    assert missing == [], f"{len(missing)} rendered files are missing"


@pytest.mark.parametrize("image", IMAGE_NAMES)
def test_a_neutral_recipe_survives_the_browser_byte_for_byte(image: str) -> None:
    """The load-bearing one, and it is about far more than arithmetic.

    A neutral recipe performs no arithmetic at all (spec §4.1), so the output must
    equal the input exactly. Which means this single assertion covers the whole
    path the golden test depends on: the PNG decoded in the browser, the texture
    upload — where a colour profile applied by default would silently rewrite the
    pixels — the row order on read-back, and the PNG written on the way out.

    If it fails, nothing below is worth reading.
    """
    with Image.open(IMAGES / f"{image}.png") as handle:
        source = np.asarray(handle.convert("RGB"), dtype=np.uint8)

    assert np.array_equal(read_rendered(image, "neutral"), source)


@pytest.mark.parametrize("entry", RECIPES, ids=lambda entry: entry["name"])
def test_the_two_renderers_agree(entry: dict) -> None:
    """One recipe across every test image, against the threshold of §8.5."""
    recipe = EditRecipe.model_validate(entry["recipe"])

    for image in IMAGE_NAMES:
        theirs = read_rendered(image, entry["name"])
        ours = quantise(render(read_source(image), recipe))

        difference = delta_e(
            ours.astype(np.float64) / 255.0, theirs.astype(np.float64) / 255.0
        )
        mean = float(difference.mean())
        worst = float(difference.max())

        assert mean < MEAN_THRESHOLD, (
            f"{image} x {entry['name']}: mean ΔE {mean:.3f} (threshold {MEAN_THRESHOLD})"
        )
        assert worst < WORST_THRESHOLD, (
            f"{image} x {entry['name']}: worst ΔE {worst:.3f} (threshold {WORST_THRESHOLD})"
        )


def test_the_curve_tables_agree_exactly() -> None:
    """Agreement without an image at all (spec §6.6).

    The delicate part of the renderer runs 1024 times in total rather than per
    pixel, which reduces the hardest question in the whole design — do two
    hand-written monotone interpolations match — to comparing two arrays of 1024
    numbers. When the test above fails, this says immediately whether the curve is
    the reason, and it does so without a picture to interpret.

    The tolerance is float32 resolution, not the ΔE budget: both sides build the
    table in double precision and store float32, so anything larger is a genuine
    difference in the algorithm.
    """
    theirs = json.loads((RENDERED / "luts.json").read_text(encoding="utf-8"))

    assert theirs, "the browser wrote no tables"

    for key, table in theirs.items():
        points = np.asarray(json.loads(key), dtype=np.float64)
        ours = build_lut(points).astype(np.float64)
        difference = np.abs(ours - np.asarray(table, dtype=np.float64))

        assert difference.max() < 1e-6, (
            f"curve {key}: tables differ by {difference.max():.2e} at index "
            f"{int(difference.argmax())}"
        )
