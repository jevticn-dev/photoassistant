"""The style fingerprint: composition, curve sampling, and the scaling constants.

The scaling tests carry the most weight. A wrong constant does not crash anything
and does not fail any other test — the distances simply stop meaning what they are
read to mean, which is the failure mode this whole file exists to make loud.
"""

import json

import numpy as np
import pytest

from photoassistant.embeddings.fingerprint import (
    COMPONENT_NAMES,
    FINGERPRINT_DIMENSION,
    RECIPE_COMPONENT_COUNT,
    Scaling,
    raw_fingerprint,
    recipe_components,
)
from photoassistant.embeddings.statistics import STATISTIC_COUNT
from photoassistant.schema import EditRecipe


def recipe(**document: object) -> EditRecipe:
    return EditRecipe.model_validate({"schema": 1, **document})


def test_the_dimension_is_thirty_and_named() -> None:
    """The number the migration writes into the column type."""
    assert RECIPE_COMPONENT_COUNT == 13
    assert STATISTIC_COUNT == 17
    assert FINGERPRINT_DIMENSION == 30
    assert len(COMPONENT_NAMES) == FINGERPRINT_DIMENSION
    assert len(set(COMPONENT_NAMES)) == FINGERPRINT_DIMENSION


def test_a_neutral_recipe_contributes_nothing() -> None:
    """Including the curve: what is stored is deviation from the diagonal.

    Storing the curve's value instead would make a neutral recipe carry 0.25, 0.5
    and 0.75 — three constants pretending to be a description.
    """
    assert np.allclose(recipe_components(recipe()), 0.0)


def test_sliders_arrive_normalised_by_their_own_limit() -> None:
    """Exposure is in stops and contrast is not, so neither may dominate."""
    components = recipe_components(
        recipe(tone={"exposure": 5.0, "contrast": 50.0}, white_balance={"temperature": -100.0})
    )

    assert components[COMPONENT_NAMES.index("exposure")] == pytest.approx(1.0)
    assert components[COMPONENT_NAMES.index("contrast")] == pytest.approx(0.5)
    assert components[COMPONENT_NAMES.index("temperature")] == pytest.approx(-1.0)


def test_the_curve_is_sampled_at_the_positions_the_fit_searches() -> None:
    """A curve lifted in the middle must read as lifted in the middle."""
    lifted = recipe(
        tone_curve={"points": [(0.0, 0.0), (0.25, 0.35), (0.5, 0.62), (0.75, 0.86), (1.0, 1.0)]}
    )

    components = recipe_components(lifted)

    assert components[COMPONENT_NAMES.index("curve_at_0.25")] == pytest.approx(0.10)
    assert components[COMPONENT_NAMES.index("curve_at_0.5")] == pytest.approx(0.12)
    assert components[COMPONENT_NAMES.index("curve_at_0.75")] == pytest.approx(0.11)


def test_curves_written_with_different_control_points_are_described_the_same() -> None:
    """Why the curve is sampled rather than copied.

    A fit with the curve enabled produces three interior points, the analytic
    starting point produces one, and a neutral recipe none. Copying control points
    would compare three different conventions; sampling asks the same question of
    all of them.
    """
    two_points = recipe(tone_curve={"points": [(0.0, 0.0), (1.0, 1.0)]})
    many_points = recipe(
        tone_curve={"points": [(0.0, 0.0), (0.25, 0.25), (0.5, 0.5), (0.75, 0.75), (1.0, 1.0)]}
    )

    assert np.allclose(recipe_components(two_points), recipe_components(many_points), atol=1e-9)


def test_the_two_halves_are_concatenated_in_order() -> None:
    statistics = np.arange(STATISTIC_COUNT, dtype=np.float64)

    vector = raw_fingerprint(recipe(tone={"exposure": 5.0}), statistics)

    assert vector.shape == (FINGERPRINT_DIMENSION,)
    assert vector[COMPONENT_NAMES.index("exposure")] == pytest.approx(1.0)
    assert np.allclose(vector[RECIPE_COMPONENT_COUNT:], statistics)


def test_the_wrong_number_of_statistics_is_refused() -> None:
    with pytest.raises(ValueError, match="17 statistics"):
        raw_fingerprint(recipe(), np.zeros(16, dtype=np.float64))


def corpus(rows: int = 200, seed: int = 7) -> np.ndarray:
    """Raw vectors whose components deliberately live on wildly different scales."""
    generator = np.random.default_rng(seed)
    scales = np.linspace(0.01, 120.0, FINGERPRINT_DIMENSION)
    offsets = np.linspace(-40.0, 40.0, FINGERPRINT_DIMENSION)
    return generator.normal(size=(rows, FINGERPRINT_DIMENSION)) * scales + offsets


def test_scaling_puts_every_component_on_the_same_footing() -> None:
    """The whole point: without this, distance measures whichever component is widest."""
    raw = corpus()

    scaling = Scaling.fit(raw)
    scaled = np.array([scaling.apply(row) for row in raw])

    assert np.allclose(scaled.mean(axis=0), 0.0, atol=1e-9)
    assert np.allclose(scaled.std(axis=0), 1.0, atol=1e-9)


def test_the_unscaled_vector_lets_one_component_outweigh_the_rest() -> None:
    """The failure this guards against, stated as a measurement rather than a worry.

    Measured over the corpus rather than over one pair of rows: a single pair says
    nothing, because any component can happen to differ a lot in one draw. What
    matters is how much of the total spread each component owns on average, and
    raw that ratio runs to five orders of magnitude.
    """
    raw = corpus()
    scaled = np.array([Scaling.fit(raw).apply(row) for row in raw])

    raw_spread = raw.var(axis=0)
    scaled_spread = scaled.var(axis=0)

    assert raw_spread.max() / raw_spread.min() > 1_000.0
    assert scaled_spread.max() / scaled_spread.min() == pytest.approx(1.0)


def test_a_component_that_never_varies_contributes_nothing_instead_of_infinity() -> None:
    raw = corpus()
    raw[:, 3] = 5.0

    scaling = Scaling.fit(raw)

    assert scaling.deviation[3] == 1.0
    assert scaling.apply(raw[0])[3] == pytest.approx(0.0)
    assert np.isfinite(scaling.apply(raw[0])).all()


def test_constants_survive_a_round_trip_through_json(tmp_path) -> None:
    """They are committed to a file, so the file is the thing that must work."""
    scaling = Scaling.fit(corpus())
    path = tmp_path / "fingerprint_scaling.json"

    scaling.save(path, generated_from=200)
    loaded = Scaling.load(path)

    assert np.allclose(loaded.mean, scaling.mean)
    assert np.allclose(loaded.deviation, scaling.deviation)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["generated_from"] == 200
    assert document["components"] == list(COMPONENT_NAMES)


def test_constants_measured_for_another_dimension_are_refused_loudly() -> None:
    """The one mistake that would otherwise be silent.

    Mixing two generations of constants in one column produces distances that are
    wrong without being detectably wrong. Better to refuse to start.
    """
    stale = Scaling.fit(corpus()).to_dict()
    stale["dimension"] = 26

    with pytest.raises(ValueError, match="Recompute the constants"):
        Scaling.from_dict(stale)


def test_a_vector_of_the_wrong_width_is_refused() -> None:
    scaling = Scaling.fit(corpus())

    with pytest.raises(ValueError, match="30 components"):
        scaling.apply(np.zeros(29, dtype=np.float64))
