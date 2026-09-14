"""The online path, in one place: photograph in, three suggestions out.

**This is the function the exam runs and the route calls.** Not two versions of it
— an evaluation that reaches past the shipped path measures a system nobody uses,
and the difference shows up later as "why is production worse than the report"
(§B60).

The whole flow is four steps and no cleverness:

1. the photograph becomes a vector — what is in the scene
2. the store returns the ``k`` nearest photographs, minus anything hidden
3. their expert edits become the candidate pool, roughly ``5k`` of them
4. the strategy picks three that differ from each other

The exclusion set is an argument of every call rather than a property of the
object, because the same recommender serves a request that hides nothing and an
exam that hides five hundred photographs, and which of those is happening is the
caller's fact, not the recommender's.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from photoassistant.recommender.interfaces import (
    Candidate,
    IEmbedder,
    IRecommendationStrategy,
    IVectorStore,
    Neighbour,
)

# Plan §7: fifty neighbouring photographs, each carrying up to five expert edits,
# so a pool of roughly 250. Both numbers are axes of the ablation.
DEFAULT_NEIGHBOURS: Final[int] = 50
DEFAULT_SUGGESTIONS: Final[int] = 3


@dataclass(frozen=True)
class Recommendation:
    """What one request produced, including what it had to choose from.

    ``pool_size`` and ``neighbours`` are kept because a suggestion set is read
    differently when it came from eleven candidates than from two hundred and
    fifty — and a pool that quietly collapses is the failure this records rather
    than hides.
    """

    suggestions: tuple[Candidate, ...]
    neighbours: tuple[Neighbour, ...]
    pool_size: int


class Recommender:
    """Embedder, store and strategy wired together. Holds no state of its own."""

    def __init__(
        self,
        embedder: IEmbedder | None,
        store: IVectorStore,
        strategy: IRecommendationStrategy,
        *,
        neighbours: int = DEFAULT_NEIGHBOURS,
        suggestions: int = DEFAULT_SUGGESTIONS,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.strategy = strategy
        self.neighbours = neighbours
        self.suggestions = suggestions

    def recommend(
        self,
        image: NDArray[np.floating],
        *,
        exclude: frozenset[str],
        strategy: IRecommendationStrategy | None = None,
    ) -> Recommendation:
        """From pixels. What the HTTP route calls.

        ``embedder`` may be absent when the caller already has vectors — the exam
        computes five hundred of them once instead of re-encoding the same
        photographs for every arm. Asking such a recommender for pixels is a
        mistake worth naming rather than an attribute error three frames down.
        """
        if self.embedder is None:
            raise ValueError(
                "this recommender was built without an embedder; "
                "call recommend_from_vector, or construct it with one"
            )

        (vector,) = self.embedder.encode([image])
        return self.recommend_from_vector(vector, exclude=exclude, strategy=strategy)

    def recommend_from_vector(
        self,
        vector: NDArray[np.floating],
        *,
        exclude: frozenset[str],
        strategy: IRecommendationStrategy | None = None,
    ) -> Recommendation:
        """From an already-computed vector.

        The exam enters here. Encoding the same five hundred photographs again for
        every one of fifteen arms would add nothing — the encoder is held fixed
        except in the arm that varies it, where the vectors are recomputed anyway —
        and the vectors it would produce are checked against the stored ones once,
        as a control, rather than assumed to match.

        ``strategy`` overrides the configured one for this call. The two-stage
        arm (ADR-23) needs rendering bound to *this* photograph, so it is built per
        request; every other arm ignores this argument.
        """
        found = self.store.neighbours(vector, count=self.neighbours, exclude=exclude)
        pool = self.store.candidates(found)
        chosen = (strategy or self.strategy).select(pool, self.suggestions)

        return Recommendation(
            suggestions=tuple(chosen),
            neighbours=tuple(found),
            pool_size=len(pool),
        )

    def describe(self) -> dict[str, object]:
        """The configuration behind a number, for the report."""
        return {
            "embedder": self.embedder.name if self.embedder else None,
            "strategy": self.strategy.name,
            "neighbours": self.neighbours,
            "suggestions": self.suggestions,
        }
