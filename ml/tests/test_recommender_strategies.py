"""The five ways of picking three, each checked on inputs with an obvious answer.

The pools here are built so that the right choice can be read off by eye: one
photograph is nearest, two candidates are style twins, a third is far from both.
A strategy that gets these wrong is wrong in a way no amount of realistic data
would make visible.
"""

import numpy as np
import pytest

from photoassistant.recommender import (
    AverageEdit,
    Candidate,
    IRecommendationStrategy,
    KMeansGroups,
    MaximalMarginalRelevance,
    RandomCandidates,
    TopCandidates,
)
from photoassistant.schema import EditRecipe


def candidate(
    identifier: str,
    reference: str,
    distance: float,
    fingerprint: tuple[float, ...] = (0.0, 0.0),
) -> Candidate:
    return Candidate(
        example_id=identifier,
        photo_reference=reference,
        expert="a",
        recipe=EditRecipe.model_validate({"schema": 1}),
        fingerprint=np.array(fingerprint, dtype=np.float64),
        after_key=None,
        photo_distance=distance,
    )


def twins_and_an_outsider() -> list[Candidate]:
    """Two nearly identical styles at the front, one distinct style behind them.

    A strategy with no diversity logic takes the twins; any strategy worth having
    takes one twin and the outsider.
    """
    return [
        candidate("near-1", "a0001", 0.10, (0.0, 0.0)),
        candidate("near-2", "a0002", 0.11, (0.01, 0.0)),
        candidate("far", "a0003", 0.30, (5.0, 5.0)),
    ]


ALL_STRATEGIES = [
    TopCandidates(),
    TopCandidates(one_per_photograph=True),
    RandomCandidates(seed=1),
    MaximalMarginalRelevance(),
    KMeansGroups(),
]


# -- shared contract ----------------------------------------------------------


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_every_strategy_satisfies_the_protocol(strategy) -> None:
    assert isinstance(strategy, IRecommendationStrategy)


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_no_strategy_ever_repeats_a_candidate(strategy) -> None:
    """Padding to three with a duplicate would show the user one thing twice."""
    chosen = strategy.select(twins_and_an_outsider(), 3)

    assert len({entry.example_id for entry in chosen}) == len(chosen)


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_no_strategy_invents_a_candidate(strategy) -> None:
    pool = twins_and_an_outsider()

    chosen = strategy.select(pool, 3)

    assert {entry.example_id for entry in chosen} <= {entry.example_id for entry in pool}


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_every_strategy_handles_an_empty_pool(strategy) -> None:
    assert strategy.select([], 3) == []


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_every_strategy_handles_a_pool_smaller_than_the_ask(strategy) -> None:
    chosen = strategy.select([candidate("only", "a0001", 0.1)], 3)

    assert len(chosen) == 1


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_every_strategy_is_deterministic(strategy) -> None:
    """Two runs of one configuration must agree, or no comparison means anything."""
    pool = twins_and_an_outsider()

    first = [entry.example_id for entry in strategy.select(pool, 2)]
    second = [entry.example_id for entry in strategy.select(list(reversed(pool)), 2)]

    assert first == second


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda s: s.name)
def test_every_strategy_is_named(strategy) -> None:
    assert strategy.name


# -- diversity, which is the whole point --------------------------------------


def test_the_baseline_takes_both_twins_and_a_real_strategy_does_not() -> None:
    """The contrast the phase exists to measure, on a pool where it is unambiguous."""
    pool = twins_and_an_outsider()

    plain = {entry.example_id for entry in TopCandidates().select(pool, 2)}
    mmr = {entry.example_id for entry in MaximalMarginalRelevance().select(pool, 2)}
    groups = {entry.example_id for entry in KMeansGroups().select(pool, 2)}

    assert plain == {"near-1", "near-2"}
    assert "far" in mmr
    assert "far" in groups


def test_mmr_starts_from_the_most_relevant_candidate() -> None:
    chosen = MaximalMarginalRelevance().select(twins_and_an_outsider(), 3)

    assert chosen[0].example_id == "near-1"


def test_lambda_one_ignores_diversity_entirely() -> None:
    """The dial has to reach the plain top-N list at its end, or it is not that dial."""
    pool = twins_and_an_outsider()

    chosen = MaximalMarginalRelevance(lambda_=1.0).select(pool, 2)

    assert [entry.example_id for entry in chosen] == ["near-1", "near-2"]


def test_lambda_zero_ignores_relevance_entirely() -> None:
    pool = twins_and_an_outsider()

    chosen = MaximalMarginalRelevance(lambda_=0.0).select(pool, 2)

    assert [entry.example_id for entry in chosen] == ["near-1", "far"]


def test_lambda_outside_its_range_is_refused() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        MaximalMarginalRelevance(lambda_=1.5)


def test_the_lambda_is_in_the_name_so_a_report_can_tell_two_runs_apart() -> None:
    assert MaximalMarginalRelevance(lambda_=0.3).name != MaximalMarginalRelevance(lambda_=0.7).name


def test_a_pool_where_every_distance_is_equal_still_chooses() -> None:
    """All five edits of one photograph share a distance, so this is the normal case (§B70)."""
    pool = [candidate(str(index), "a0001", 0.2, (float(index), 0.0)) for index in range(5)]

    chosen = MaximalMarginalRelevance().select(pool, 3)

    assert len(chosen) == 3
    assert len({entry.example_id for entry in chosen}) == 3


def test_kmeans_groups_are_ordered_by_their_best_member() -> None:
    """A user reads top to bottom, so the first suggestion is the most relevant."""
    pool = twins_and_an_outsider()

    chosen = KMeansGroups().select(pool, 2)

    assert chosen[0].photo_distance <= chosen[1].photo_distance


# -- the floors ---------------------------------------------------------------


def test_random_draws_the_same_three_for_the_same_pool_in_any_order() -> None:
    """Derived from the pool, not from a counter — eight parallel workers agree."""
    pool = [candidate(str(index), f"a{index:04d}", index / 10.0) for index in range(20)]

    strategy = RandomCandidates(seed=5)
    first = [entry.example_id for entry in strategy.select(pool, 3)]
    second = [entry.example_id for entry in strategy.select(list(reversed(pool)), 3)]

    assert first == second


def test_random_with_another_seed_draws_something_else() -> None:
    """A seed that changes nothing would make the floor a single fixed sample."""
    pool = [candidate(str(index), f"a{index:04d}", index / 10.0) for index in range(20)]

    first = [entry.example_id for entry in RandomCandidates(seed=1).select(pool, 3)]
    second = [entry.example_id for entry in RandomCandidates(seed=2).select(pool, 3)]

    assert first != second


def test_random_does_not_simply_return_the_nearest() -> None:
    pool = [candidate(str(index), f"a{index:04d}", index / 10.0) for index in range(20)]

    chosen = [entry.example_id for entry in RandomCandidates(seed=3).select(pool, 3)]

    assert chosen != ["0", "1", "2"]


def test_the_average_edit_answers_the_same_thing_whatever_it_is_given() -> None:
    fixed = candidate("average", "", 0.0)
    strategy = AverageEdit(fixed)

    assert strategy.select(twins_and_an_outsider(), 3) == [fixed]
    assert strategy.select([], 3) == [fixed]


def test_the_average_edit_returns_one_suggestion_rather_than_three_copies() -> None:
    """Three identical previews would satisfy the count and mean nothing."""
    chosen = AverageEdit(candidate("average", "", 0.0)).select(twins_and_an_outsider(), 3)

    assert len(chosen) == 1
