"""``IRecommendationStrategy`` implementations.

This file starts with the one that does the least: take the nearest, ignore
whether they differ. It is not a placeholder — plan §8 makes it a **mandatory
baseline**, because every diversity method has to be read against what happens
without any.

MMR, k-means and the two-stage render-aware selection (ADR-23) join it in tasks 5
and 5b, and the remaining baselines in task 4.
"""

from collections.abc import Sequence

from photoassistant.recommender.interfaces import Candidate


class TopCandidates:
    """The ``count`` best-ranked candidates, with no regard for diversity.

    Expected to be the **worst** arm on diversity and quite possibly the **best**
    on closeness to an expert, since it takes the most relevant candidates there
    are. That combination is not a contradiction, it is the reason both measures
    are reported: an arm that wins one and loses the other solves half the problem
    (§B56).

    **Two variants, because the plain one has a structural quirk worth separating
    out.** The pool holds up to five edits of the same photograph, all at the same
    scene distance, so "the three best" are routinely three experts editing the
    *same* scene. That is the honest degenerate answer and stays the default.

    With ``one_per_photograph`` the pick is spread across scenes instead. It costs
    one line and answers the question a reader will ask: how much of the diversity
    a real strategy produces is just "do not show the same photograph three
    times"? If this variant already clears the diversity threshold, MMR has to
    beat *it*, not the degenerate one.

    Ties are broken by example id rather than left to the order the database
    returned, so a run is reproducible.
    """

    def __init__(self, *, one_per_photograph: bool = False) -> None:
        self.one_per_photograph = one_per_photograph

    @property
    def name(self) -> str:
        return "top-per-scene" if self.one_per_photograph else "top"

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        if count <= 0:
            return []

        ranked = sorted(
            candidates,
            key=lambda candidate: (candidate.photo_distance, candidate.example_id),
        )

        chosen: list[Candidate] = []
        seen: set[str] = set()
        for candidate in ranked:
            if self.one_per_photograph:
                if candidate.photo_reference in seen:
                    continue
                seen.add(candidate.photo_reference)
            chosen.append(candidate)
            if len(chosen) == count:
                break
        return chosen
