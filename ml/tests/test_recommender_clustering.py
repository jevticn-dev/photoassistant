"""k-means: does it find groups that are there, and behave when they are not.

Written against inputs whose right answer is obvious by construction, because a
clustering test over realistic data can only check that the code ran.
"""

import numpy as np

from photoassistant.recommender import kmeans


def three_clumps(seed: int = 0) -> np.ndarray:
    """Thirty points in three tight, far-apart clumps."""
    generator = np.random.default_rng(seed)
    centres = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    return np.vstack([centre + generator.normal(scale=0.1, size=(10, 2)) for centre in centres])


def test_obvious_groups_are_found() -> None:
    labels = kmeans(three_clumps(), 3, seed=1)

    # Points 0-9, 10-19 and 20-29 must each end up with one label of their own.
    groups = [set(labels[start : start + 10]) for start in (0, 10, 20)]
    assert all(len(group) == 1 for group in groups)
    assert len({group.pop() for group in groups}) == 3


def test_the_same_seed_gives_the_same_grouping() -> None:
    points = three_clumps()

    assert np.array_equal(kmeans(points, 3, seed=7), kmeans(points, 3, seed=7))


def test_fewer_points_than_groups_returns_one_group_each() -> None:
    """Padding an empty cluster into existence would claim a kind of thing that is not there."""
    labels = kmeans(np.array([[0.0, 0.0], [1.0, 1.0]]), 3, seed=1)

    assert sorted(labels) == [0, 1]


def test_identical_points_do_not_break_the_split() -> None:
    """k-means++ divides by the total squared distance, which is zero here."""
    labels = kmeans(np.zeros((10, 4)), 3, seed=1)

    assert len(labels) == 10


def test_an_empty_pool_has_no_labels() -> None:
    assert len(kmeans(np.zeros((0, 3)), 3, seed=1)) == 0


def test_asking_for_no_groups_returns_nothing() -> None:
    assert len(kmeans(three_clumps(), 0, seed=1)) == 0


def test_every_point_gets_a_label_inside_the_range() -> None:
    labels = kmeans(three_clumps(), 3, seed=3)

    assert len(labels) == 30
    assert set(labels) <= {0, 1, 2}


def test_one_group_puts_everything_together() -> None:
    assert set(kmeans(three_clumps(), 1, seed=2)) == {0}
