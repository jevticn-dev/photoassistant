"""Where a candidate's fingerprint comes from — the axis of the ablation.

One of these tests exists because the code was wrong and nothing caught it: blocks
were scaled by the square root of their width, which assumes unit variance per
component. That holds for the z-scored thirty and not for an L2-normalised neural
block, so the neural side came out twenty times too small and contributed nothing.
The arm reproduced the plain one to every decimal and looked like a finding.

The test below pins the property that was violated: **after joining, each block
contributes according to its weight, not according to how wide it is** (§B63).
"""

import numpy as np
import pytest

from photoassistant.recommender import Candidate
from photoassistant.recommender import fingerprints as fp
from photoassistant.schema import EditRecipe


def candidate(identifier: str = "1", fingerprint=None, **extra) -> Candidate:
    return Candidate(
        example_id=identifier,
        photo_reference="a0001",
        expert="a",
        recipe=EditRecipe.model_validate({"schema": 1}),
        fingerprint=np.arange(30, dtype=np.float64) if fingerprint is None else fingerprint,
        after_key=None,
        photo_distance=0.1,
        **extra,
    )


# -- the free compositions ----------------------------------------------------


def test_the_recipe_half_is_the_first_thirteen() -> None:
    taken = fp.sliced(fp.RECIPE_SLICE)(candidate())

    assert taken.tolist() == list(range(13))


def test_the_statistics_half_is_the_remaining_seventeen() -> None:
    taken = fp.sliced(fp.STATISTICS_SLICE)(candidate())

    assert taken.tolist() == list(range(13, 30))


def test_the_two_halves_reassemble_into_the_stored_vector() -> None:
    entry = candidate()

    halves = np.concatenate(
        [fp.sliced(fp.RECIPE_SLICE)(entry), fp.sliced(fp.STATISTICS_SLICE)(entry)]
    )

    assert halves.tolist() == fp.stored(entry).tolist()


# -- joining blocks, which is where the defect was ----------------------------


def test_a_wide_block_does_not_swallow_a_narrow_one() -> None:
    """The property the first version broke, stated directly.

    One block of 30 numbers with values around 1, one of 384 with unit norm: left
    alone, the first would dominate a distance by its magnitude and the second by
    its width. Joined, each must carry its weight and nothing else.
    """
    narrow = np.full(30, 1.0)
    wide = np.full(384, 1.0 / np.sqrt(384))  # unit norm, like an encoder's output

    joined = fp.blocks(
        (lambda _: narrow, 1.0),
        (lambda _: wide, 1.0),
    )(candidate())

    first, second = joined[:30], joined[30:]
    assert np.linalg.norm(first) == pytest.approx(1.0)
    assert np.linalg.norm(second) == pytest.approx(1.0)


def test_weights_change_how_much_a_block_counts() -> None:
    join = fp.blocks(
        (lambda _: np.full(10, 1.0), 1.0),
        (lambda _: np.full(10, 1.0), 3.0),
    )
    joined = join(candidate())

    assert np.linalg.norm(joined[10:]) == pytest.approx(3.0 * np.linalg.norm(joined[:10]))


def test_a_block_of_zeros_does_not_divide_by_zero() -> None:
    joined = fp.blocks((lambda _: np.zeros(5), 1.0), (lambda _: np.ones(5), 1.0))(candidate())

    assert np.isfinite(joined).all()


# -- fingerprints computed offline --------------------------------------------


@pytest.fixture
def stored_file(tmp_path):
    path = tmp_path / "arm.npz"
    np.savez_compressed(
        path,
        identifiers=np.array(["1", "2"]),
        vectors=np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )
    return path


def test_a_computed_arm_is_looked_up_by_example(stored_file) -> None:
    vectors = fp.StoredVectors(stored_file)

    assert vectors(candidate("2")).tolist() == [0.0, 1.0]
    assert vectors.dimension == 2
    assert len(vectors) == 2


def test_a_candidate_missing_from_the_arm_is_refused(stored_file) -> None:
    """Zeros would make it look maximally different from everything — the most
    flattering possible failure."""
    vectors = fp.StoredVectors(stored_file)

    with pytest.raises(KeyError, match="no fingerprint"):
        vectors(candidate("absent"))


# -- the store wrapper --------------------------------------------------------


class FakeStore:
    def __init__(self, pool):
        self.pool = pool
        self.asked = None

    def neighbours(self, vector, *, count, exclude):
        self.asked = (count, exclude)
        return ["neighbour"]

    def candidates(self, neighbours):
        return list(self.pool)


def test_restamping_changes_the_ruler_and_nothing_else() -> None:
    pool = [candidate("1"), candidate("2")]
    inner = FakeStore(pool)

    restamped = fp.RestampedStore(inner, fp.sliced(fp.RECIPE_SLICE)).candidates(["n"])

    assert [entry.example_id for entry in restamped] == ["1", "2"]
    assert [entry.photo_distance for entry in restamped] == [0.1, 0.1]
    assert restamped[0].fingerprint.shape == (13,)


def test_the_search_itself_is_passed_straight_through() -> None:
    """The ablation changes what "different" means, never which scenes are found."""
    inner = FakeStore([])

    fp.RestampedStore(inner, fp.stored).neighbours(np.zeros(3), count=7, exclude=frozenset({"x"}))

    assert inner.asked == (7, frozenset({"x"}))
