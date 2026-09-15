"""The leakage measurement, including proof that it can see an effect at all.

The measurement's expected answer is "almost nothing", which is the most dangerous
kind of expected answer: a comparison that silently compares something with itself
also reports almost nothing. Phase 2 lost five hours to exactly that shape of
mistake (notes §B50), so the positive control here is not decoration — a doubled
deviation must show up as a halved distance.

Pure functions over arrays; no database.
"""

import numpy as np
import pytest
from photoassistant.embeddings.fingerprint import FINGERPRINT_DIMENSION, Scaling

from pipeline.measure_split_leakage import compare_constants, compare_distances


def stack(rows: int = 2000, seed: int = 0) -> np.ndarray:
    generator = np.random.default_rng(seed)
    return generator.normal(size=(rows, FINGERPRINT_DIMENSION))


def test_identical_constants_move_no_distance_at_all():
    vectors = stack()

    change = compare_distances(vectors, vectors)["relative_change_percent"]

    assert change["worst"] == pytest.approx(0.0, abs=1e-9)


def test_a_doubled_deviation_halves_the_distance():
    """The positive control: the comparison must be able to report a real change."""
    vectors = stack()

    change = compare_distances(vectors, vectors / 2.0)["relative_change_percent"]

    assert change["median"] == pytest.approx(50.0, abs=1e-6)
    assert change["worst"] == pytest.approx(50.0, abs=1e-6)


def test_a_shift_common_to_every_vector_changes_no_distance():
    """Distances are what the recommender uses, and they do not see a shared offset."""
    vectors = stack()

    change = compare_distances(vectors, vectors + 5.0)["relative_change_percent"]

    assert change["worst"] == pytest.approx(0.0, abs=1e-9)


def test_the_same_constants_compare_as_unchanged():
    scaling = Scaling.fit(stack())

    comparison = compare_constants(scaling, scaling)

    assert comparison["deviation_ratio"]["median"] == pytest.approx(1.0)
    assert comparison["worst_component"]["deviation_ratio"] == pytest.approx(1.0)
    assert comparison["mean_shift_in_deviations"]["worst"] == pytest.approx(0.0)


def test_the_worst_component_is_the_one_that_moved_most():
    raw = stack()
    original = Scaling.fit(raw)

    widened = Scaling(
        mean=original.mean.copy(),
        deviation=original.deviation.copy(),
    )
    widened.deviation[7] *= 1.5

    comparison = compare_constants(original, widened)

    assert comparison["worst_component"]["deviation_ratio"] == pytest.approx(1.5)
