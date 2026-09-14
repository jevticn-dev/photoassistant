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
    RenderAwareSelection,
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


# -- two-stage, render-aware selection (ADR-23) -------------------------------


def flat_lab(lightness: float) -> np.ndarray:
    return np.tile(np.array([lightness, 0.0, 0.0], dtype=np.float64), (4, 4, 1))


def render_by_id(mapping: dict[str, float]):
    """A stand-in renderer: each candidate becomes a flat patch of a given lightness.

    Real rendering is tested in phase 1 and costs 59 ms a go. What needs proving
    here is the *selection* — that a candidate which renders the same as one
    already chosen loses its slot — and that is visible on flat patches.
    """
    return lambda candidate: flat_lab(mapping[candidate.example_id])


def test_the_second_stage_drops_a_candidate_that_renders_the_same() -> None:
    """The risk ADR-23 exists for: different fingerprints, identical on screen."""
    pool = [
        candidate("a", "a0001", 0.10, (0.0, 0.0)),
        candidate("b", "a0002", 0.11, (9.0, 9.0)),  # far by fingerprint...
        candidate("c", "a0003", 0.12, (0.2, 0.2)),
    ]
    # ...but renders exactly like "a", while "c" renders differently.
    renders = {"a": 50.0, "b": 50.0, "c": 80.0}

    inner = MaximalMarginalRelevance(lambda_=0.0)
    chosen = RenderAwareSelection(inner, render_by_id(renders), finalists=3).select(pool, 2)

    assert [entry.example_id for entry in chosen] == ["a", "c"]
    assert [entry.example_id for entry in inner.select(pool, 2)] == ["a", "b"]


def test_the_first_suggestion_is_still_the_inner_strategy_s_best() -> None:
    pool = [candidate(name, f"a000{index}", 0.1 * index, (float(index), 0.0))
            for index, name in enumerate("abcd", start=1)]
    renders = {"a": 10.0, "b": 40.0, "c": 70.0, "d": 95.0}

    chosen = RenderAwareSelection(
        TopCandidates(), render_by_id(renders), finalists=4
    ).select(pool, 3)

    assert chosen[0].example_id == "a"


def test_a_shortlist_no_longer_than_the_ask_is_returned_unrendered() -> None:
    """Nothing to choose between, so nothing is rendered — 59 ms a go is not free."""
    pool = [candidate("a", "a0001", 0.1), candidate("b", "a0002", 0.2)]
    rendered: list[str] = []

    def render(entry):
        rendered.append(entry.example_id)
        return flat_lab(50.0)

    chosen = RenderAwareSelection(TopCandidates(), render, finalists=2).select(pool, 2)

    assert len(chosen) == 2
    assert rendered == []


def test_it_renders_the_shortlist_and_not_the_whole_pool() -> None:
    """250 candidates at 59 ms is 15 seconds a request; six is 0,35 s (§B66)."""
    pool = [candidate(str(index), f"a{index:04d}", index / 100.0) for index in range(50)]
    rendered: list[str] = []

    def render(entry):
        rendered.append(entry.example_id)
        return flat_lab(float(entry.example_id))

    RenderAwareSelection(TopCandidates(), render, finalists=6).select(pool, 3)

    assert len(rendered) == 6


def test_the_name_says_which_inner_strategy_and_how_many_finalists() -> None:
    name = RenderAwareSelection(
        MaximalMarginalRelevance(lambda_=0.3), render_by_id({}), finalists=6
    ).name

    assert "mmr-0.3" in name
    assert "6" in name


def test_a_shortlist_of_zero_finalists_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RenderAwareSelection(TopCandidates(), render_by_id({}), finalists=0)


# -- choosing within a scene (the late finding, §B79) -------------------------


def fitted(identifier: str, reference: str, fit_error: float) -> Candidate:
    """Two edits of one photograph differ only in how well v1 reproduced them."""
    return Candidate(
        example_id=identifier,
        photo_reference=reference,
        expert="a",
        recipe=EditRecipe.model_validate({"schema": 1}),
        fingerprint=np.zeros(2),
        after_key=None,
        photo_distance=0.10,
        fit_error=fit_error,
    )


def test_by_default_the_edit_within_a_scene_is_chosen_arbitrarily() -> None:
    """Deterministic, but by identifier — measured at 18/24/20/17/21% per expert."""
    pool = [fitted("b", "a0001", 0.5), fitted("a", "a0001", 9.0)]

    (chosen,) = TopCandidates(one_per_photograph=True).select(pool, 1)

    assert chosen.example_id == "a"


def test_preferring_the_best_fit_takes_the_faithfully_reproduced_edit() -> None:
    """A recipe v1 reproduced well is a truer record of what the expert did."""
    pool = [fitted("b", "a0001", 0.5), fitted("a", "a0001", 9.0)]

    (chosen,) = TopCandidates(one_per_photograph=True, prefer_best_fit=True).select(pool, 1)

    assert chosen.example_id == "b"


def test_the_scene_still_comes_before_the_fit() -> None:
    """Relevance is not traded away: a nearer scene wins even with a worse fit."""
    near = fitted("near", "a0001", 9.0)
    far = Candidate(
        example_id="far", photo_reference="a0002", expert="a",
        recipe=EditRecipe.model_validate({"schema": 1}), fingerprint=np.zeros(2),
        after_key=None, photo_distance=0.90, fit_error=0.1,
    )

    chosen = TopCandidates(one_per_photograph=True, prefer_best_fit=True).select([far, near], 2)

    assert [entry.example_id for entry in chosen] == ["near", "far"]


def test_a_candidate_without_a_fit_error_does_not_break_the_ordering() -> None:
    """Nineteen edits were never fitted; they must not sort as infinitely good."""
    pool = [fitted("fitted", "a0001", 2.0), candidate("unfitted", "a0001", 0.10)]

    chosen = TopCandidates(one_per_photograph=True, prefer_best_fit=True).select(pool, 1)

    assert len(chosen) == 1


def test_the_two_variants_are_named_apart_as_well() -> None:
    assert (
        TopCandidates(one_per_photograph=True).name
        != TopCandidates(one_per_photograph=True, prefer_best_fit=True).name
    )
