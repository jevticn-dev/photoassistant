"""What the exam measures, as plain functions over already-prepared inputs.

Two questions, both needed, because either one alone is trivially gamed: three
random edits are perfectly diverse and worthless, and three copies of the corpus
average are safely close and offer no choice (§B56).

    diversity   how far apart the three suggestions are
    closeness   how near the best of them lands to something an expert did

**Everything here takes CIELAB arrays, never sRGB images.** That is deliberate and
it is the shape of the whole harness: a perceptual comparison costs 176 ms of
which 56 ms is the two conversions, so the caller converts each image **once** and
passes the result around. A function that accepted images would quietly convert
the same expert rendition fifteen times per photograph (§B55).

**Nothing here renders, reads a file, or touches the database.** The expensive,
side-effecting parts belong to the harness; this module is arithmetic, so its
tests need no fixtures and its numbers can be checked by hand.
"""

from collections.abc import Sequence
from itertools import combinations

import numpy as np
from numpy.typing import NDArray

from photoassistant.embeddings.fingerprint import recipe_components
from photoassistant.renderer import ciede2000
from photoassistant.schema import EditRecipe


def mean_delta_e(lab_a: NDArray[np.floating], lab_b: NDArray[np.floating]) -> float:
    """Mean perceptual difference between two images, both already in CIELAB.

    ΔE ≈ 1 is the threshold of noticing (§B6), which is the number every result in
    this module is read against: two suggestions 0,8 apart are one suggestion
    shown twice.
    """
    return float(ciede2000(lab_a, lab_b).mean())


def mean_pairwise_delta_e(labs: Sequence[NDArray[np.floating]]) -> float | None:
    """Average difference across every pair — diversity, on screen.

    Used twice with the same meaning, which is why it is one function: over the
    three suggestions it is *our* diversity, and over five expert renditions of the
    same photograph it is the **human disagreement** that gives our number a scale
    (§B56).

    ``None`` for fewer than two images. Not zero: one suggestion is not a set of
    identical suggestions, and a zero in that column would read as "we measured
    perfect sameness" rather than "there was nothing to compare".
    """
    if len(labs) < 2:
        return None
    return float(np.mean([mean_delta_e(a, b) for a, b in combinations(labs, 2)]))


def median_pairwise_delta_e(labs: Sequence[NDArray[np.floating]]) -> float | None:
    """The middle pair rather than the average one — the hit threshold (decision C).

    Median because five experts produce ten pairs and one of them is regularly an
    outlier: a single expert who went somewhere nobody else did would drag an
    average threshold up and make every arm look successful on that photograph.
    """
    if len(labs) < 2:
        return None
    return float(np.median([mean_delta_e(a, b) for a, b in combinations(labs, 2)]))


def mean_pairwise_distance(vectors: Sequence[NDArray[np.floating]]) -> float | None:
    """The same idea in fingerprint space — diversity as the *selection* sees it.

    Reported next to the rendered figure rather than instead of it. Where the two
    disagree, the fingerprint is seeing something the renderer cannot reproduce,
    which is the risk ADR-23 exists to size.
    """
    if len(vectors) < 2:
        return None
    stack = [np.asarray(vector, dtype=np.float64) for vector in vectors]
    return float(np.mean([float(np.linalg.norm(a - b)) for a, b in combinations(stack, 2)]))


def relative_to_experts(value: float | None, expert_value: float | None) -> float | None:
    """Express a diversity figure as a fraction of what the experts did.

    **This is what makes the two diversity numbers comparable at all.** One is in
    ΔE, the other in standardised fingerprint units; subtracting them, as ADR-23
    loosely says, would subtract apples from kilograms. Divided by the expert
    disagreement *measured in the same space*, both become dimensionless — "we are
    0,9 times as varied as five people are" — and the gap between the two ratios
    is the size of the risk, in a unit that means something.

    1,0 is the target: our three suggestions differ about as much as five experts
    differ on the same photograph. Far below is one suggestion shown three times;
    far above is outside the range people actually work in (§B39).
    """
    if value is None or expert_value is None or expert_value <= 0.0:
        return None
    return value / expert_value


def best_delta_e_per_suggestion(
    suggestion_labs: Sequence[NDArray[np.floating]],
    expert_labs: Sequence[NDArray[np.floating]],
) -> list[float]:
    """For each suggestion, its distance to the **nearest** expert rendition.

    Nearest, because the five experts disagree with each other: a suggestion close
    to any one of them is in the space of what a competent person did. The set of
    right answers is plural by construction (§B39).
    """
    return [
        min(mean_delta_e(suggestion, expert) for expert in expert_labs)
        for suggestion in suggestion_labs
    ]


def closeness(
    suggestion_labs: Sequence[NDArray[np.floating]],
    expert_labs: Sequence[NDArray[np.floating]],
) -> float | None:
    """The best of the three — not their average.

    The question is "did at least one suggestion land where a person actually
    went", not "were all three good". Averaging would punish exactly the variety
    the system is built to offer.
    """
    if not suggestion_labs or not expert_labs:
        return None
    return min(best_delta_e_per_suggestion(suggestion_labs, expert_labs))


def recipe_distance(first: EditRecipe, second: EditRecipe) -> float:
    """Distance between two recipes in parameter space — the cheap metric (plan §8).

    Uses the same thirteen numbers the fingerprint's first half is built from —
    sliders divided by their own limits, the curve sampled at three fixed points —
    so "far apart" means the same thing here as it does everywhere else in the
    system rather than being a second convention (§B24).

    Cheap, and **not a substitute**. Whether it agrees with the perceptual figure
    is itself one of the phase's findings; where they disagree, the disagreement is
    reported rather than resolved in favour of the convenient one.
    """
    return float(np.linalg.norm(recipe_components(first) - recipe_components(second)))
