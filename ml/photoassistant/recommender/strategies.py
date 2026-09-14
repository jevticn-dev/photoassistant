"""``IRecommendationStrategy`` implementations — everything that picks three.

Five arms live here, and they answer the same question in deliberately different
ways so that the ablation can say which one earns its place:

============================  ==========================================
``TopCandidates``             the nearest, diversity ignored — baseline
``RandomCandidates``          three at random — the floor
``AverageEdit``               always the same edit — the other floor
``MaximalMarginalRelevance``  good **and** different, one at a time (ADR-11)
``KMeansGroups``              three natural groups, the best of each
============================  ==========================================

The two-stage render-aware selection from ADR-23 joins them once the harness can
render, since both need the same piece of machinery and writing it twice is how
two versions of one formula start drifting apart.

**Two measurements, not one.** A strategy that wins on diversity and loses on
closeness to an expert has solved half the problem, which is why the baselines are
mandatory rather than decorative: three random edits are perfectly diverse and
perfectly useless, and always-the-average is safely near and offers no choice at
all (§B56).
"""

import hashlib
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from photoassistant.recommender.clustering import kmeans
from photoassistant.recommender.interfaces import Candidate


# Ties are broken by example id everywhere in this file. Scene distance is a
# property of the photograph, so all five edits of one photograph carry the same
# number and "the best" among them is otherwise decided by whatever order the
# database returned (§B70) — which is not an order, and not reproducible.
def _ranked(candidates: Sequence[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda entry: (entry.photo_distance, entry.example_id))


def _normalised(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Map values onto 0..1 within this pool, where 1 is best.

    Relevance and similarity are measured in two different spaces — cosine
    distance between CLIP vectors on one side, Euclidean distance between
    fingerprints on the other — with different ranges. Added together raw, one
    term quietly dominates and λ stops meaning what it says (§B61).

    A pool where every value is identical carries no information, and gets zeros
    rather than a division by zero: the term simply stops contributing and the
    decision falls to the other one.
    """
    if len(values) == 0:
        return values
    span = float(values.max() - values.min())
    if span <= 0.0:
        return np.zeros_like(values)
    return (values - values.min()) / span


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
    beat *it*, not the degenerate one (§B70).
    """

    def __init__(self, *, one_per_photograph: bool = False) -> None:
        self.one_per_photograph = one_per_photograph

    @property
    def name(self) -> str:
        return "top-per-scene" if self.one_per_photograph else "top"

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        if count <= 0:
            return []

        chosen: list[Candidate] = []
        seen: set[str] = set()
        for candidate in _ranked(candidates):
            if self.one_per_photograph:
                if candidate.photo_reference in seen:
                    continue
                seen.add(candidate.photo_reference)
            chosen.append(candidate)
            if len(chosen) == count:
                break
        return chosen


class RandomCandidates:
    """Three at random: the floor every other arm has to clear.

    Random is **maximally diverse and worth nothing**, which is exactly why plan
    §8 makes it mandatory. A diversity number that a coin flip matches is not
    evidence of anything.

    **The seed is derived from the pool, not carried in a counter.** The harness
    runs photographs across eight processes, so a strategy holding a running
    generator would produce different suggestions depending on which worker
    happened to take which photograph — reproducible only by accident. Hashing the
    candidate ids gives the same draw for the same pool, in any process, in any
    order.

    Two ways to use it, and they answer different questions. Given the retrieved
    pool it measures *selection* with retrieval kept; given a random sample of the
    corpus it measures the whole system against no retrieval at all. Which pool it
    receives is the harness's decision, and the report names it.
    """

    name = "random"

    def __init__(self, *, seed: int) -> None:
        self.seed = seed

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        if count <= 0 or not candidates:
            return []

        ordered = _ranked(candidates)
        identity = f"{self.seed}:" + ",".join(entry.example_id for entry in ordered)
        digest = hashlib.sha256(identity.encode("utf-8")).digest()
        generator = np.random.default_rng(int.from_bytes(digest[:8], "big"))

        picked = generator.permutation(len(ordered))[: min(count, len(ordered))]
        return [ordered[index] for index in picked]


class AverageEdit:
    """Always the same edit, whatever the photograph — the other floor.

    It answers a question the hit metric has to survive: how well does one safe,
    corpus-average correction do on its own? FiveK edits are corrective, so the
    average of them is a real contender on closeness, and any arm that fails to
    beat it is not recommending, it is averaging.

    **It returns one suggestion, not three copies.** Repeating the same recipe
    would satisfy "three" while showing the user one thing three times, and every
    other arm is held to that rule. Its diversity is therefore not defined rather
    than zero, and the report says so instead of printing a number it did not
    measure.

    The average recipe itself is data, so it arrives as an argument: the harness
    computes it once over the build set, and a strategy stays a strategy rather
    than a thing that also reads the corpus.
    """

    name = "average"

    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        # The pool is ignored, and that is the entire arm: whatever was retrieved,
        # the answer is the same edit. Named and discarded rather than left out of
        # the signature, which has to match the protocol.
        del candidates
        return [self.candidate] if count > 0 else []


class MaximalMarginalRelevance:
    """Good **and** different, chosen one at a time (ADR-11, the default arm).

    Each pick scores every remaining candidate as::

        score = lambda * relevance  -  (1 - lambda) * similarity to what is chosen

    where relevance is closeness of the source scene to the query and similarity is
    closeness of the style fingerprint to the nearest already-chosen suggestion.
    Both are normalised inside the pool first, so ``lambda`` means what it says
    (§B61).

    ``lambda = 1`` is the plain top-N list; ``lambda = 0`` ignores quality
    entirely. The default of 0.5 is a starting point, not a finding — λ is one of
    the axes of the ablation.

    The first pick is the most relevant candidate: with nothing chosen yet there is
    nothing to differ from, and starting anywhere else would throw away the one
    thing the search is sure about.
    """

    def __init__(self, *, lambda_: float = 0.5) -> None:
        if not 0.0 <= lambda_ <= 1.0:
            raise ValueError(f"lambda must be between 0 and 1, got {lambda_}")
        self.lambda_ = lambda_

    @property
    def name(self) -> str:
        return f"mmr-{self.lambda_:g}"

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        if count <= 0 or not candidates:
            return []

        ordered = _ranked(candidates)
        if len(ordered) <= 1:
            return list(ordered[:count])

        # Distance is "worse", so relevance is what is left of 1 after it.
        relevance = 1.0 - _normalised(
            np.array([entry.photo_distance for entry in ordered], dtype=np.float64)
        )

        fingerprints = np.array([entry.fingerprint for entry in ordered], dtype=np.float64)
        gaps = np.linalg.norm(fingerprints[:, None, :] - fingerprints[None, :, :], axis=2)
        similarity = 1.0 - _normalised(gaps)

        chosen = [0]
        remaining = list(range(1, len(ordered)))

        while len(chosen) < count and remaining:
            best_index = None
            best_score = -np.inf
            for index in remaining:
                penalty = float(similarity[index, chosen].max())
                score = self.lambda_ * float(relevance[index]) - (1.0 - self.lambda_) * penalty
                # Strictly greater keeps the first candidate on a tie, and the pool
                # is already ordered by (distance, id), so ties resolve the same
                # way on every run.
                if score > best_score:
                    best_score, best_index = score, index
            chosen.append(best_index)
            remaining.remove(best_index)

        return [ordered[index] for index in chosen]


class KMeansGroups:
    """Three natural groups in the pool, the most relevant member of each.

    The other reading of "make them different" (ADR-11). Where MMR picks greedily
    and pushes away from what it already has, this one looks at the **shape** of
    the pool first: if the candidates really fall into three camps it will find
    them, and if they are smeared evenly its three groups are arbitrary.

    Which reading is better is not something theory settles, which is why both are
    implemented and measured rather than argued about.

    Groups are ordered by their best member, so the first suggestion is still the
    most relevant one overall — a user reads top to bottom.
    """

    name = "kmeans"

    def __init__(self, *, seed: int = 20260913) -> None:
        self.seed = seed

    def select(self, candidates: Sequence[Candidate], count: int) -> list[Candidate]:
        if count <= 0 or not candidates:
            return []

        ordered = _ranked(candidates)
        fingerprints = np.array([entry.fingerprint for entry in ordered], dtype=np.float64)
        labels = kmeans(fingerprints, count, seed=self.seed)

        # The pool is already sorted by relevance, so the first member of each
        # group encountered is that group's best.
        best: dict[int, Candidate] = {}
        for label, candidate in zip(labels, ordered, strict=True):
            best.setdefault(int(label), candidate)

        return sorted(
            best.values(),
            key=lambda entry: (entry.photo_distance, entry.example_id),
        )[:count]
