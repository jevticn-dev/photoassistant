"""``IVectorStore`` over pgvector, inside the Postgres that already holds the rows.

ADR-5 chose this over a dedicated vector database: the search is joined to
relational data on every query — which expert, which fit error, which tags — and
two systems would mean two sources of truth for one answer. On 5.000 vectors of
512 numbers the index is not even a speed-up yet; the whole column is about 10 MB
and an exact scan answers in the same 13 ms (§B54). It is there for the order of
magnitude that comes later.

**The connection is passed in, never opened here.** Its lifetime belongs to
whoever owns the process: one per worker in the offline pipeline, a pooled one in
the service. The library takes what it needs as an argument and has no ambient
state (`.claude/rules/ml_service.md`).
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from photoassistant.recommender.interfaces import Candidate, Neighbour
from photoassistant.schema import EditRecipe

# Vectors are passed as text and cast on the SQL side, as phase 2 writes them:
# the literal format is [1,2,3] and stable, and it keeps the pgvector adapter
# package out of a dependency list for three lines of work.
NEIGHBOURS_SQL = """
SELECT p.id, p.source_reference, p.clip_embedding <=> %(query)s::vector AS distance
  FROM photos p
 WHERE p.clip_embedding IS NOT NULL
   AND NOT (coalesce(p.source_reference, '') = ANY(%(exclude)s))
 ORDER BY p.clip_embedding <=> %(query)s::vector
 LIMIT %(count)s
"""

CANDIDATES_SQL = """
SELECT e.id, p.source_reference, e.expert, e.edit,
       e.style_fingerprint::text, e.after_key, e.fit_error
  FROM examples e
  JOIN photos p ON p.id = e.photo_id
 WHERE p.source_reference = ANY(%(references)s)
   AND NOT e.excluded_from_fitting
   AND e.style_fingerprint IS NOT NULL
   AND e.edit IS NOT NULL
 ORDER BY p.source_reference, e.expert
"""


def as_vector_literal(values: NDArray[np.floating]) -> str:
    return "[" + ",".join(repr(float(value)) for value in np.asarray(values).ravel()) + "]"


def parse_vector(literal: str) -> NDArray[np.float64]:
    return np.fromstring(literal.strip("[]"), sep=",", dtype=np.float64)


class PostgresVectorStore:
    """Search and fetch against the migrated schema. Reads only; never writes."""

    def __init__(self, connection) -> None:
        self._connection = connection

    # -- search ---------------------------------------------------------------

    def neighbours(
        self,
        vector: NDArray[np.floating],
        *,
        count: int,
        exclude: frozenset[str],
    ) -> list[Neighbour]:
        """The ``count`` nearest photographs, excluding the references given.

        **The exclusion changes the query plan**, and the evaluation has to know
        that rather than discover it: with a filter Postgres drops the HNSW index
        and scans all rows exactly, which is a *better* answer by a different
        route than the one production takes (§B54). Both paths are measured in
        task 13; neither is silently assumed to stand for the other.

        The ``coalesce`` is not decoration either. A user's upload has no source
        reference, and ``NULL = ANY(...)`` is NULL rather than false, so without
        it every uploaded photograph would quietly drop out of its own search.
        """
        if count <= 0:
            return []

        parameters = {
            "query": as_vector_literal(vector),
            "exclude": sorted(exclude),
            "count": count,
        }
        with self._connection.cursor() as cursor:
            cursor.execute(NEIGHBOURS_SQL, parameters)
            return [
                Neighbour(reference=reference, photo_id=str(identifier), distance=float(distance))
                for identifier, reference, distance in cursor.fetchall()
            ]

    # -- fetch ----------------------------------------------------------------

    def candidates(self, neighbours: Sequence[Neighbour]) -> list[Candidate]:
        """Every usable edit of those photographs, each carrying its scene distance.

        The distance travels with the candidate because the strategy needs it:
        "how good is this one" is how close its scene was to the query, and
        looking it up again later would mean keeping two structures in step.
        """
        if not neighbours:
            return []

        distances = {neighbour.reference: neighbour.distance for neighbour in neighbours}

        with self._connection.cursor() as cursor:
            cursor.execute(CANDIDATES_SQL, {"references": sorted(distances)})
            rows = cursor.fetchall()

        candidates = [
            Candidate(
                example_id=str(identifier),
                photo_reference=reference,
                expert=expert,
                recipe=EditRecipe.model_validate(edit),
                fingerprint=parse_vector(fingerprint),
                after_key=after_key,
                photo_distance=distances[reference],
                fit_error=None if fit_error is None else float(fit_error),
            )
            for identifier, reference, expert, edit, fingerprint, after_key, fit_error in rows
        ]
        # Nearest scene first, so a strategy that simply takes the head of the
        # list is already the "top-N without diversity" baseline rather than an
        # arbitrary order that happens to come out of the database.
        candidates.sort(key=lambda candidate: (candidate.photo_distance, candidate.example_id))
        return candidates


class MatrixVectorStore:
    """Search over vectors held in memory; candidates still come from the database.

    The search encoder ablation needs somewhere to put 5.000 DINOv2 vectors, and
    ``photos.clip_embedding`` is ``vector(512)`` holding CLIP. Rather than migrate a
    column for an experiment (decision D, the same rule as for fingerprints), the
    vectors live in a file and the search runs here.

    **Exact, not approximate, and that is not a compromise.** Measured in this
    phase: 5.000 vectors of 512 numbers is about 10 MB, and an exact scan answers in
    the same 13 ms as the HNSW index (§B54). One matrix multiply is if anything
    simpler than what Postgres does.

    Only ``neighbours`` is answered here. Everything else about a candidate — the
    recipe, the fingerprint, the fitting error — lives in the database and is
    fetched by the store this one wraps, so the two halves cannot drift apart.
    """

    def __init__(self, references: Sequence[str], vectors: NDArray[np.floating], inner) -> None:
        if len(references) != len(vectors):
            raise ValueError(
                f"{len(references)} references against {len(vectors)} vectors"
            )
        self.references = list(references)
        # Normalised once here so the search is a dot product. The encoders already
        # return unit vectors; doing it again costs nothing and means a file written
        # by something else cannot silently change what "distance" means (§B44).
        stack = np.asarray(vectors, dtype=np.float64)
        norms = np.linalg.norm(stack, axis=1, keepdims=True)
        self.vectors = stack / np.where(norms > 0.0, norms, 1.0)
        self._inner = inner

    def neighbours(
        self,
        vector: NDArray[np.floating],
        *,
        count: int,
        exclude: frozenset[str],
    ) -> list[Neighbour]:
        if count <= 0:
            return []

        query = np.asarray(vector, dtype=np.float64)
        norm = float(np.linalg.norm(query))
        similarity = self.vectors @ (query / norm if norm > 0.0 else query)

        # Cosine distance, so that the numbers mean the same thing they do coming
        # out of pgvector and a strategy cannot tell which store it is talking to.
        distances = 1.0 - similarity
        allowed = [
            index for index in np.argsort(distances) if self.references[index] not in exclude
        ]
        return [
            Neighbour(
                reference=self.references[index],
                photo_id=self.references[index],
                distance=float(distances[index]),
            )
            for index in allowed[:count]
        ]

    def candidates(self, neighbours: Sequence[Neighbour]) -> list[Candidate]:
        return self._inner.candidates(neighbours)
