"""Scoring one photograph and summing five hundred of them.

Flat CIELAB patches again, so every expected number can be worked out by hand:
a patch at L*=50 and one at L*=60 are about ten apart, and the hit rule is a
comparison between two such numbers.
"""

import json

import numpy as np
import pytest

from photoassistant.recommender import (
    Candidate,
    ExpertScales,
    PhotographScore,
    Recommendation,
    aggregate,
    hit_rate_curve,
    score_photograph,
    slice_by,
)
from photoassistant.schema import EditRecipe


def patch(lightness: float) -> np.ndarray:
    return np.tile(np.array([lightness, 0.0, 0.0], dtype=np.float64), (4, 4, 1))


def candidate(identifier: str, reference: str, fingerprint=(0.0, 0.0), **edit) -> Candidate:
    return Candidate(
        example_id=identifier,
        photo_reference=reference,
        expert="a",
        recipe=EditRecipe.model_validate({"schema": 1, **edit}),
        fingerprint=np.array(fingerprint, dtype=np.float64),
        after_key=None,
        photo_distance=0.1,
    )


def recommendation(*candidates: Candidate, pool_size: int = 250) -> Recommendation:
    return Recommendation(suggestions=candidates, neighbours=(), pool_size=pool_size)


SCALES = ExpertScales(mean_delta_e=8.0, median_delta_e=8.5, fingerprint_mean=5.0)


def score(
    suggestions=("a", "b", "c"),
    rendered=(50.0, 60.0, 70.0),
    experts=(52.0,),
    scales: ExpertScales = SCALES,
) -> PhotographScore:
    chosen = [candidate(name, f"a000{index}") for index, name in enumerate(suggestions, start=1)]
    return score_photograph(
        "a0731",
        recommendation(*chosen),
        [patch(value) for value in rendered],
        [patch(value) for value in experts],
        [candidate("expert", "a0731")],
        scales,
    )


# -- the hit rule -------------------------------------------------------------


def test_a_suggestion_nearer_than_the_experts_are_to_each_other_is_a_hit() -> None:
    """Closest suggestion is 2 lightness units from the expert; the bar is 8,5."""
    result = score(rendered=(50.0, 80.0, 95.0), experts=(52.0,))

    assert result.closeness_delta_e < result.threshold
    assert result.hit is True


def test_a_suggestion_further_away_than_that_is_not() -> None:
    result = score(rendered=(20.0, 80.0, 95.0), experts=(52.0,))

    assert result.closeness_delta_e > result.threshold
    assert result.hit is False


def test_the_bar_is_this_photograph_s_own_expert_disagreement() -> None:
    """Same suggestions, two photographs: the strict one fails, the lenient passes."""
    strict = ExpertScales(mean_delta_e=3.0, median_delta_e=3.0, fingerprint_mean=5.0)
    lenient = ExpertScales(mean_delta_e=18.0, median_delta_e=18.0, fingerprint_mean=5.0)

    assert score(rendered=(45.0, 80.0, 95.0), experts=(52.0,), scales=strict).hit is False
    assert score(rendered=(45.0, 80.0, 95.0), experts=(52.0,), scales=lenient).hit is True


def test_with_no_expert_to_compare_against_the_hit_is_undecided_not_false() -> None:
    """False would count as a miss and drag the rate down for a missing measurement."""
    result = score_photograph(
        "a0731", recommendation(candidate("a", "a0001")), [patch(50.0)], [], [], SCALES
    )

    assert result.hit is None
    assert result.closeness_delta_e is None


# -- diversity, both ways -----------------------------------------------------


def test_diversity_is_reported_against_the_human_scale() -> None:
    """1,0 means "as varied as five people are on this photograph" (§B72)."""
    result = score(rendered=(50.0, 60.0, 70.0))

    assert result.diversity_ratio == pytest.approx(
        result.diversity_rendered / SCALES.mean_delta_e
    )


def test_the_fingerprint_side_uses_its_own_scale() -> None:
    """Different units, so each is divided by the experts measured in that unit."""
    chosen = [
        candidate("a", "a0001", fingerprint=(0.0, 0.0)),
        candidate("b", "a0002", fingerprint=(10.0, 0.0)),
    ]
    result = score_photograph(
        "a0731",
        recommendation(*chosen),
        [patch(50.0), patch(60.0)],
        [patch(52.0)],
        [],
        SCALES,
    )

    assert result.diversity_fingerprint == pytest.approx(10.0)
    assert result.fingerprint_ratio == pytest.approx(10.0 / SCALES.fingerprint_mean)


def test_one_suggestion_has_no_diversity_to_report() -> None:
    """The always-average arm lands here, and gets no number rather than a zero."""
    result = score(suggestions=("a",), rendered=(50.0,))

    assert result.diversity_rendered is None
    assert result.diversity_ratio is None


# -- what each row carries ----------------------------------------------------


def test_a_row_records_what_produced_it() -> None:
    result = score()

    assert result.suggestions == ("a", "b", "c")
    assert result.sources == ("a0001", "a0002", "a0003")
    assert result.pool_size == 250


def test_a_row_survives_a_round_trip_through_json() -> None:
    """Rows are stored so that slices and thresholds are a regrouping, not a rerun."""
    document = json.loads(json.dumps(score().to_dict()))

    assert document["reference"] == "a0731"
    assert document["hit"] in (True, False)


# -- aggregation --------------------------------------------------------------


def rows(hits: list[bool], closeness: list[float]) -> list[PhotographScore]:
    return [
        PhotographScore(
            reference=f"a{index:04d}",
            pool_size=250,
            suggestions=("x",),
            experts=("a",),
            sources=("a0001",),
            diversity_rendered=4.0,
            diversity_fingerprint=5.0,
            diversity_ratio=0.5,
            fingerprint_ratio=1.0,
            closeness_delta_e=value,
            closeness_recipe=0.5,
            threshold=8.5,
            hit=hit,
        )
        for index, (hit, value) in enumerate(zip(hits, closeness, strict=True))
    ]


def test_the_hit_rate_is_the_share_that_hit() -> None:
    summary = aggregate(rows([True, True, False, False], [1.0, 2.0, 9.0, 9.0]))

    assert summary["hit_rate"] == pytest.approx(0.5)


def test_undecided_photographs_do_not_count_as_misses() -> None:
    scores = rows([True, False], [1.0, 9.0])
    scores.append(
        PhotographScore(
            reference="a9999", pool_size=0, suggestions=(), experts=(), sources=(),
            diversity_rendered=None, diversity_fingerprint=None, diversity_ratio=None,
            fingerprint_ratio=None, closeness_delta_e=None, closeness_recipe=None,
            threshold=None, hit=None,
        )
    )

    assert aggregate(scores)["hit_rate"] == pytest.approx(0.5)


def test_the_gap_is_how_much_variety_fails_to_survive_rendering() -> None:
    """fingerprint 1,0 against rendered 0,5: half of what the selection saw (ADR-23)."""
    summary = aggregate(rows([True], [1.0]))

    assert summary["diversity_gap"]["median"] == pytest.approx(0.5)


def test_the_curve_rises_with_the_threshold_and_is_reported_whole() -> None:
    curve = hit_rate_curve(rows([True, True, False], [1.0, 4.0, 15.0]))

    rates = [point["rate"] for point in curve]
    assert rates == sorted(rates)

    at = {point["threshold"]: point["rate"] for point in curve}
    assert at[0.5] == pytest.approx(0.0)      # nothing is that close
    assert at[5.0] == pytest.approx(2 / 3)    # the two at 1,0 and 4,0
    assert at[20.0] == pytest.approx(1.0)     # the experts disagree by up to 19,9


def test_the_curve_of_nothing_is_empty_rather_than_flat_zero() -> None:
    assert hit_rate_curve([]) == []


# -- slices -------------------------------------------------------------------


def test_a_slice_carries_its_size_and_says_when_it_is_too_small() -> None:
    scores = rows([True] * 5, [1.0] * 5)
    labels = {score.reference: "portrait" for score in scores}

    sliced = slice_by(scores, labels, minimum=30)

    assert sliced["portrait"]["n"] == 5
    assert sliced["portrait"]["indicative_only"] is True


def test_a_large_enough_slice_is_not_marked_indicative() -> None:
    scores = rows([True] * 40, [1.0] * 40)
    labels = {score.reference: "nature" for score in scores}

    assert slice_by(scores, labels, minimum=30)["nature"]["indicative_only"] is False


def test_photographs_without_a_label_are_left_out_of_every_slice() -> None:
    """A fifth of the corpus carries tags; the rest must not become a category."""
    scores = rows([True] * 4, [1.0] * 4)
    labels = {scores[0].reference: "nature"}

    sliced = slice_by(scores, labels)

    assert set(sliced) == {"nature"}
    assert sliced["nature"]["n"] == 1
