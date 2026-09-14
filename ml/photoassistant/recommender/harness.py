"""Scoring one photograph, and turning five hundred scores into a result.

Split from the runner on purpose. Everything here is arithmetic over prepared
values — no database, no object store, no rendering — so the exam's logic can be
tested on numbers worked out by hand, while the expensive machinery that feeds it
lives in ``pipeline/evaluate.py``.

**Per-photograph results are kept, not just the totals.** Slices by category, a
different threshold, a question nobody has asked yet: all of those are a regrouping
of stored rows rather than a second run of the exam (phase 3, decision I).
"""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self

import numpy as np
from numpy.typing import NDArray

from photoassistant.recommender.interfaces import Candidate
from photoassistant.recommender.metrics import (
    closeness,
    mean_pairwise_delta_e,
    mean_pairwise_distance,
    recipe_distance,
    relative_to_experts,
)
from photoassistant.recommender.recommend import Recommendation

# The hit-rate curve is reported over this range rather than at one point, so the
# conclusion can be read without depending on where the threshold was put (§B56).
# It reaches 20 because the experts themselves disagree by up to 19,9 ΔE.
CURVE_THRESHOLDS: tuple[float, ...] = tuple(round(0.5 * step, 1) for step in range(1, 41))


@dataclass(frozen=True)
class ExpertScales:
    """What the five experts did on one photograph, from the frozen artefact.

    Three numbers, three jobs (§B56): the mean is the scale diversity is expressed
    against, the median is the hit threshold, and the fingerprint mean is the scale
    for the other diversity figure so the two can be compared at all (§B72).
    """

    mean_delta_e: float
    median_delta_e: float
    fingerprint_mean: float

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> Self:
        return cls(
            mean_delta_e=float(document["human_mean"]),
            median_delta_e=float(document["human_median"]),
            fingerprint_mean=float(document["fingerprint_mean"]),
        )

    @classmethod
    def load_all(cls, path: Path) -> dict[str, Self]:
        """Every photograph's scales, keyed by reference."""
        document = json.loads(path.read_text(encoding="utf-8"))
        return {
            reference: cls.from_dict(entry)
            for reference, entry in document["per_photograph"].items()
            if entry.get("human_mean") is not None
        }


@dataclass(frozen=True)
class PhotographScore:
    """One row of the exam. Everything an aggregate might later want."""

    reference: str
    pool_size: int
    suggestions: tuple[str, ...]
    experts: tuple[str | None, ...]
    sources: tuple[str, ...]

    diversity_rendered: float | None
    diversity_fingerprint: float | None
    diversity_ratio: float | None
    fingerprint_ratio: float | None

    closeness_delta_e: float | None
    closeness_recipe: float | None
    threshold: float | None
    hit: bool | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_photograph(
    reference: str,
    recommendation: Recommendation,
    rendered_labs: Sequence[NDArray[np.floating]],
    expert_labs: Sequence[NDArray[np.floating]],
    expert_recipes: Sequence[Candidate],
    scales: ExpertScales,
) -> PhotographScore:
    """Both measures for one photograph, plus what produced them.

    ``rendered_labs`` are the suggestions applied to *this* photograph and
    converted once; ``expert_labs`` are the five stored results, likewise. Nothing
    is converted twice, which is the difference between twelve minutes an arm and
    twenty-eight (§B55).
    """
    chosen = recommendation.suggestions

    rendered = mean_pairwise_delta_e(rendered_labs)
    fingerprint = mean_pairwise_distance([entry.fingerprint for entry in chosen])
    best = closeness(rendered_labs, expert_labs)

    parametric = None
    if chosen and expert_recipes:
        parametric = min(
            recipe_distance(suggestion.recipe, expert.recipe)
            for suggestion in chosen
            for expert in expert_recipes
        )

    return PhotographScore(
        reference=reference,
        pool_size=recommendation.pool_size,
        suggestions=tuple(entry.example_id for entry in chosen),
        experts=tuple(entry.expert for entry in chosen),
        sources=tuple(entry.photo_reference for entry in chosen),
        diversity_rendered=rendered,
        diversity_fingerprint=fingerprint,
        diversity_ratio=relative_to_experts(rendered, scales.mean_delta_e),
        fingerprint_ratio=relative_to_experts(fingerprint, scales.fingerprint_mean),
        closeness_delta_e=best,
        closeness_recipe=parametric,
        threshold=scales.median_delta_e,
        # A suggestion counts when it is nearer to some expert than the experts
        # typically are to each other on this same photograph — "as close as one
        # person is to another", with no constant chosen by anybody (decision C).
        hit=None if best is None else best < scales.median_delta_e,
    )


def _distribution(values: list[float]) -> dict[str, float]:
    array = np.array([value for value in values if value is not None], dtype=np.float64)
    if not len(array):
        return {}
    return {
        "count": int(len(array)),
        "p10": float(np.percentile(array, 10)),
        "median": float(np.median(array)),
        "mean": float(array.mean()),
        "p90": float(np.percentile(array, 90)),
    }


def hit_rate_curve(scores: Sequence[PhotographScore]) -> list[dict[str, float]]:
    """Share of photographs with a hit, as a function of where the bar is put.

    Reported in full because a single threshold is a lever: choose it after seeing
    the numbers and it picks the winner. If one arm's curve lies above another's
    along its whole length, the conclusion does not depend on the threshold at all,
    and if they cross, that is worth seeing rather than hiding behind one point.
    """
    values = [score.closeness_delta_e for score in scores if score.closeness_delta_e is not None]
    if not values:
        return []

    array = np.array(values, dtype=np.float64)
    return [
        {"threshold": threshold, "rate": float((array < threshold).mean())}
        for threshold in CURVE_THRESHOLDS
    ]


def aggregate(scores: Sequence[PhotographScore]) -> dict[str, Any]:
    """One arm's result: the headline numbers, the curve, and what was missing."""
    decided = [score for score in scores if score.hit is not None]

    return {
        "photographs": len(scores),
        "hit_rate": (
            float(np.mean([score.hit for score in decided])) if decided else None
        ),
        "closeness_delta_e": _distribution([s.closeness_delta_e for s in scores]),
        "closeness_recipe": _distribution([s.closeness_recipe for s in scores]),
        "diversity_rendered": _distribution([s.diversity_rendered for s in scores]),
        "diversity_ratio": _distribution([s.diversity_ratio for s in scores]),
        "diversity_fingerprint": _distribution([s.diversity_fingerprint for s in scores]),
        "fingerprint_ratio": _distribution([s.fingerprint_ratio for s in scores]),
        "pool_size": _distribution([float(s.pool_size) for s in scores]),
        "suggestions_returned": _distribution([float(len(s.suggestions)) for s in scores]),
        # How many different photographs the suggestions came from. Without it the
        # diversity ratio is ambiguous at exactly the place it matters: three edits
        # of ONE scene score about 1,0 by construction, because "how far apart five
        # experts are on one photograph" is the very quantity the scale is made of
        # (§B75).
        "distinct_sources": _distribution(
            [float(len(set(s.sources))) for s in scores if s.sources]
        ),
        # The gap ADR-23 is about: how much of the variety the fingerprint sees
        # fails to survive rendering, both sides expressed against the experts.
        "diversity_gap": _gap(scores),
        "hit_rate_curve": hit_rate_curve(scores),
    }


def _gap(scores: Sequence[PhotographScore]) -> dict[str, float]:
    pairs = [
        score.fingerprint_ratio - score.diversity_ratio
        for score in scores
        if score.fingerprint_ratio is not None and score.diversity_ratio is not None
    ]
    return _distribution(pairs)


def slice_by(
    scores: Sequence[PhotographScore],
    labels: dict[str, str],
    *,
    minimum: int = 30,
) -> dict[str, Any]:
    """The same aggregate per category, with ``n`` attached to every one.

    Categories come from the catalogue and only a fifth of the corpus carries any,
    so most slices are small. Every one reports its size, and those under
    ``minimum`` are marked as indicative rather than presented as findings — a
    slice of four is not a measurement (§B59).
    """
    grouped: dict[str, list[PhotographScore]] = {}
    for score in scores:
        label = labels.get(score.reference)
        if label:
            grouped.setdefault(label, []).append(score)

    return {
        label: {
            "n": len(group),
            "indicative_only": len(group) < minimum,
            **aggregate(group),
        }
        for label, group in sorted(grouped.items())
    }
