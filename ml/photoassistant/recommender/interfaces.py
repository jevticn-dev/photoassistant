"""The three seams of the recommender, and the values that travel between them.

Each arm of the ablation study is **another implementation of one of these**, never
a branch inside an ``if``. That is the whole reason they exist: an experiment that
lives in a conditional cannot be run twice side by side, cannot be named in a
report, and quietly rots the moment a fourth arm appears.

    IEmbedder                 picture in, vector out — "what is in this scene"
    IVectorStore              vector in, neighbours out; then their edits
    IRecommendationStrategy   many candidates in, three out

The flow reads left to right: the query photograph is embedded, the store finds
the ``k`` most similar photographs and hands back the expert edits belonging to
them, and the strategy picks three that differ from each other (§A17).

**Why protocols rather than base classes.** An arm is often a thin wrapper around
something that already exists — the CLIP encoder from phase 2, a psycopg
connection — and requiring it to inherit from our class would mean writing an
adapter whose only job is to satisfy a type. Structural typing asks for the
methods and nothing else.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from photoassistant.schema import EditRecipe


@dataclass(frozen=True)
class Neighbour:
    """One photograph the search considered similar to the query.

    ``distance`` is cosine distance over L2-normalised CLIP vectors: 0 is the same
    direction, 1 is unrelated, 2 is opposite. Kept rather than turned into a
    similarity score, because it is what the database returned and every
    conversion is a place for a convention to drift.
    """

    reference: str
    photo_id: str
    distance: float


@dataclass(frozen=True)
class Candidate:
    """One expert edit that could be suggested, with everything needed to judge it.

    ``recipe`` is what would be applied to the user's photograph — the only part
    that is transferable (§B49). ``fingerprint`` is how this edit is told apart
    from the others, and ``photo_distance`` is how close the scene it came from
    was to the query; a strategy weighs the two against each other.

    ``after_key`` points at the expert's own 512px result. The online path never
    reads it; the evaluation does, because that image is the key the suggestion is
    marked against (ADR-24).
    """

    example_id: str
    photo_reference: str
    expert: str | None
    recipe: EditRecipe
    fingerprint: NDArray[np.float64]
    after_key: str | None
    photo_distance: float
    # How faithfully schema v1 reproduced this expert's result when it was fitted
    # (phase 2). Carried because it is the only per-candidate quality signal that
    # exists: all five edits of one photograph share a scene distance, so without
    # it "the best of the five" has nothing to mean.
    fit_error: float | None = None


@runtime_checkable
class IEmbedder(Protocol):
    """Turns images into vectors of a fixed width.

    Arms: CLIP (default, ADR-5 path), DINOv2, and a combination. ``name`` and
    ``dimension`` exist so a report can say which arm produced a number without
    the harness having to know the concrete class.
    """

    @property
    def name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def encode(self, images: Sequence[NDArray[np.floating]]) -> NDArray[np.float32]:
        """Encode images, each height x width x 3 in [0, 1], one row per image."""
        ...


@runtime_checkable
class IVectorStore(Protocol):
    """Nearest-neighbour search, and the edits belonging to what it found.

    Two methods rather than one because the two questions are separate: ``k`` is a
    knob on the search alone, and the recall measurement needs the search without
    the fetch. pgvector inside Postgres is the default (ADR-5); Qdrant would be
    another implementation of exactly this.
    """

    def neighbours(
        self,
        vector: NDArray[np.floating],
        *,
        count: int,
        exclude: frozenset[str],
    ) -> list[Neighbour]:
        """The ``count`` most similar photographs, nearest first.

        ``exclude`` is **not optional and has no default**. Forgetting it is the
        one mistake that makes an evaluation look excellent while measuring
        nothing: the held-out photograph finds itself, and the expert's own edit
        comes back as a suggestion (decision A). An empty set is written out
        explicitly, so that the absence of hiding is a decision on the page rather
        than a missing argument.
        """
        ...

    def candidates(self, neighbours: Sequence[Neighbour]) -> list[Candidate]:
        """Every usable expert edit of those photographs.

        Usable means fitted and fingerprinted: the nineteen edits that schema v1
        cannot express have no recipe worth suggesting. A photograph whose edits
        are all excluded therefore contributes nothing, which is why it can be a
        neighbour but never an exam question.
        """
        ...


@runtime_checkable
class IRecommendationStrategy(Protocol):
    """Picks the suggestions out of the candidate pool.

    Arms: MMR over fingerprints (default, ADR-11), k-means into three groups, the
    two-stage render-aware selection (ADR-23), and the mandatory baselines —
    top-N without diversity, three at random, always-the-average-edit.
    """

    @property
    def name(self) -> str: ...

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        """Choose ``count`` candidates, best first.

        **Returning fewer than asked is allowed and returning duplicates is not.**
        A pool can be smaller than three — a small ``k``, a photograph whose edits
        were excluded, an aggressive filter — and padding the answer with a repeat
        would hand the user the same suggestion twice while the response claims
        three. The caller is told what there was.
        """
        ...
