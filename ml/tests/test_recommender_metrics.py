"""The exam's arithmetic, on inputs whose answer can be worked out by hand.

CIELAB is convenient here: ``L*`` alone is lightness, and two flat patches that
differ only in ``L*`` have a CIEDE2000 difference close to that difference. So a
"grey at 50" and a "grey at 60" are about 10 apart, and a test can say so.
"""

import numpy as np
import pytest

from photoassistant.recommender import (
    closeness,
    mean_delta_e,
    mean_pairwise_delta_e,
    mean_pairwise_distance,
    median_pairwise_delta_e,
    recipe_distance,
    relative_to_experts,
)
from photoassistant.recommender.metrics import best_delta_e_per_suggestion
from photoassistant.schema import EditRecipe


def patch(lightness: float, a: float = 0.0, b: float = 0.0) -> np.ndarray:
    """A flat 4x4 image in CIELAB."""
    return np.tile(np.array([lightness, a, b], dtype=np.float64), (4, 4, 1))


def recipe(**document: object) -> EditRecipe:
    return EditRecipe.model_validate({"schema": 1, **document})


# -- one pair -----------------------------------------------------------------


def test_an_image_is_identical_to_itself() -> None:
    assert mean_delta_e(patch(50.0), patch(50.0)) == pytest.approx(0.0)


def test_a_lightness_difference_shows_up_at_roughly_its_size() -> None:
    """Sanity anchor: ΔE ≈ 1 is the threshold of noticing, so the scale matters."""
    difference = mean_delta_e(patch(50.0), patch(60.0))

    assert 5.0 < difference < 12.0


# -- diversity ----------------------------------------------------------------


def test_three_identical_suggestions_have_no_diversity() -> None:
    labs = [patch(50.0)] * 3

    assert mean_pairwise_delta_e(labs) == pytest.approx(0.0)


def test_diversity_averages_every_pair_not_just_neighbours() -> None:
    """Three patches at 50, 60 and 70: pairs are 50-60, 50-70 and 60-70."""
    labs = [patch(50.0), patch(60.0), patch(70.0)]

    pairwise = [
        mean_delta_e(labs[0], labs[1]),
        mean_delta_e(labs[0], labs[2]),
        mean_delta_e(labs[1], labs[2]),
    ]

    assert mean_pairwise_delta_e(labs) == pytest.approx(float(np.mean(pairwise)))


def test_a_single_suggestion_has_undefined_diversity_rather_than_zero() -> None:
    """Zero would read as "measured perfect sameness" — the average-edit arm hits this."""
    assert mean_pairwise_delta_e([patch(50.0)]) is None
    assert mean_pairwise_delta_e([]) is None


def test_fingerprint_diversity_is_the_same_idea_in_the_other_space() -> None:
    vectors = [np.array([0.0, 0.0]), np.array([3.0, 4.0])]

    assert mean_pairwise_distance(vectors) == pytest.approx(5.0)


def test_fingerprint_diversity_needs_two_as_well() -> None:
    assert mean_pairwise_distance([np.array([1.0])]) is None


# -- the threshold ------------------------------------------------------------


def test_the_threshold_is_the_middle_pair_not_the_average_one() -> None:
    """One expert who went somewhere nobody else did must not raise the bar for all."""
    labs = [patch(50.0), patch(51.0), patch(52.0), patch(95.0)]

    median = median_pairwise_delta_e(labs)
    mean = mean_pairwise_delta_e(labs)

    assert median is not None and mean is not None
    assert median < mean


def test_the_threshold_needs_two_experts() -> None:
    """A single expert disagrees with nobody, which is why the split needs two (task 1)."""
    assert median_pairwise_delta_e([patch(50.0)]) is None


# -- closeness ----------------------------------------------------------------


def test_closeness_takes_the_best_suggestion_not_the_average_one() -> None:
    """One good suggestion among three is a success; averaging would punish variety."""
    suggestions = [patch(50.0), patch(90.0), patch(20.0)]
    experts = [patch(51.0)]

    assert closeness(suggestions, experts) == pytest.approx(
        mean_delta_e(patch(50.0), patch(51.0))
    )


def test_a_suggestion_is_measured_against_the_nearest_expert() -> None:
    """Five experts disagree; being close to any one of them counts (§B39)."""
    suggestions = [patch(80.0)]
    experts = [patch(20.0), patch(79.0), patch(40.0)]

    (best,) = best_delta_e_per_suggestion(suggestions, experts)

    assert best == pytest.approx(mean_delta_e(patch(80.0), patch(79.0)))


def test_closeness_without_suggestions_or_without_experts_is_undefined() -> None:
    assert closeness([], [patch(50.0)]) is None
    assert closeness([patch(50.0)], []) is None


# -- the comparison that makes two units comparable ---------------------------


def test_matching_the_experts_exactly_is_one() -> None:
    """1,0 is the target: as varied as five people are on the same photograph."""
    assert relative_to_experts(4.0, 4.0) == pytest.approx(1.0)


def test_half_as_varied_as_the_experts_is_a_half() -> None:
    assert relative_to_experts(2.0, 4.0) == pytest.approx(0.5)


def test_a_ratio_needs_something_to_divide_by() -> None:
    assert relative_to_experts(2.0, None) is None
    assert relative_to_experts(None, 4.0) is None
    assert relative_to_experts(2.0, 0.0) is None


# -- the cheap metric ---------------------------------------------------------


def test_the_same_recipe_is_at_no_distance_from_itself() -> None:
    assert recipe_distance(recipe(), recipe()) == pytest.approx(0.0)


def test_a_stronger_slider_is_further_away() -> None:
    neutral = recipe()
    mild = recipe(tone={"exposure": 0.5})
    strong = recipe(tone={"exposure": 2.0})

    assert recipe_distance(neutral, mild) < recipe_distance(neutral, strong)


def test_recipe_distance_does_not_care_which_way_round_it_is_asked() -> None:
    first = recipe(tone={"contrast": 30})
    second = recipe(color={"saturation": -20})

    assert recipe_distance(first, second) == pytest.approx(recipe_distance(second, first))
