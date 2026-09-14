"""The seams themselves: what conforms, what travels through them, and the baseline.

No database and no model — everything here is structure and arithmetic. The claim
that the pgvector store really searches is in ``test_recommender_store.py``, which
needs Postgres.
"""

import numpy as np

from photoassistant.recommender import (
    Candidate,
    ClipEmbedder,
    IEmbedder,
    IRecommendationStrategy,
    IVectorStore,
    Neighbour,
    PostgresVectorStore,
    TopCandidates,
)
from photoassistant.recommender.stores import as_vector_literal, parse_vector
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
        after_key=f"fivek/{reference}/after512-a.png",
        photo_distance=distance,
    )


# -- conformance --------------------------------------------------------------


def test_the_implementations_satisfy_the_protocols() -> None:
    """Structural typing is only worth something if something is checked against it."""
    assert isinstance(ClipEmbedder(encoder=object()), IEmbedder)
    assert isinstance(PostgresVectorStore(connection=object()), IVectorStore)
    assert isinstance(TopCandidates(), IRecommendationStrategy)


def test_importing_the_recommender_does_not_need_torch() -> None:
    """The embedder names its model without loading a gigabyte of weights.

    ``dimension`` reaches into the phase 2 module, which imports torch lazily, so
    this also proves the encoder is not constructed just by asking about it.
    """
    embedder = ClipEmbedder(encoder=object())
    assert embedder.name == "clip"


# -- values -------------------------------------------------------------------


def test_a_vector_survives_the_trip_through_a_postgres_literal() -> None:
    vector = np.array([0.5, -0.25, 1.0 / 3.0], dtype=np.float64)

    assert np.allclose(parse_vector(as_vector_literal(vector)), vector)


def test_neighbours_and_candidates_are_values_not_records_to_mutate() -> None:
    """Frozen on purpose: a candidate is passed to several strategies in a row."""
    first = Neighbour(reference="a0001", photo_id="x", distance=0.1)
    second = Neighbour(reference="a0001", photo_id="x", distance=0.1)

    assert first == second


# -- the baseline -------------------------------------------------------------


def test_the_baseline_takes_the_nearest_scenes_in_order() -> None:
    pool = [
        candidate("3", "a0003", 0.30),
        candidate("1", "a0001", 0.10),
        candidate("2", "a0002", 0.20),
    ]

    chosen = TopCandidates().select(pool, 2)

    assert [entry.example_id for entry in chosen] == ["1", "2"]


def test_the_plain_baseline_may_return_three_edits_of_one_photograph() -> None:
    """The degenerate answer is the point of this baseline, not a defect in it.

    Five experts edited the same scene at the same distance, so "the three best"
    are three edits of one photograph. Hiding that would make the baseline look
    better than no-diversity-logic actually is.
    """
    pool = [candidate(str(index), "a0001", 0.10) for index in range(5)]

    chosen = TopCandidates().select(pool, 3)

    assert len({entry.photo_reference for entry in chosen}) == 1
    assert len(chosen) == 3


def test_the_per_scene_variant_spreads_across_photographs() -> None:
    pool = [candidate(f"{index}", "a0001", 0.10) for index in range(5)]
    pool += [candidate("late", "a0002", 0.90)]

    chosen = TopCandidates(one_per_photograph=True).select(pool, 3)

    assert [entry.photo_reference for entry in chosen] == ["a0001", "a0002"]


def test_the_two_variants_are_named_apart() -> None:
    """A report has to be able to say which one produced a number."""
    assert TopCandidates().name != TopCandidates(one_per_photograph=True).name


def test_a_small_pool_returns_what_there_is_rather_than_a_repeat() -> None:
    """Padding with a duplicate would show the user one suggestion twice."""
    pool = [candidate("1", "a0001", 0.1)]

    chosen = TopCandidates().select(pool, 3)

    assert len(chosen) == 1


def test_an_empty_pool_selects_nothing() -> None:
    assert TopCandidates().select([], 3) == []


def test_asking_for_nothing_returns_nothing() -> None:
    assert TopCandidates().select([candidate("1", "a0001", 0.1)], 0) == []


def test_the_choice_does_not_depend_on_the_order_rows_arrived_in() -> None:
    """Ties are broken by example id, so two runs agree."""
    pool = [candidate(identifier, f"a000{identifier}", 0.5) for identifier in "3142"]

    first = TopCandidates().select(pool, 2)
    second = TopCandidates().select(list(reversed(pool)), 2)

    assert [entry.example_id for entry in first] == [entry.example_id for entry in second]


# -- the walk width, which pgvector will not warn about -----------------------


class RecordingCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, parameters=None):
        self.log.append(statement.strip().split("\n")[0])

    def fetchall(self):
        return []


class RecordingConnection:
    def __init__(self):
        self.statements: list[str] = []

    def cursor(self):
        return RecordingCursor(self.statements)


def widths(statements: list[str]) -> list[int]:
    return [
        int(statement.rsplit("=", 1)[1])
        for statement in statements
        if statement.startswith("SET hnsw.ef_search")
    ]


def test_the_walk_is_widened_before_asking_for_more_than_it_would_return() -> None:
    """pgvector returns at most ef_search rows, defaulting to 40, without a word.

    Measured before the fix: asking for 50 gave 40 and asking for 100 gave 40, so
    the pool was a fifth smaller than the configuration said and recall against
    exact search sat at exactly 0,80 on every query.
    """
    connection = RecordingConnection()

    PostgresVectorStore(connection).neighbours(
        np.zeros(512), count=50, exclude=frozenset()
    )

    assert widths(connection.statements) == [100]


def test_a_small_request_needs_no_widening() -> None:
    """The default already covers it, and a SET costs a round trip."""
    connection = RecordingConnection()

    PostgresVectorStore(connection).neighbours(
        np.zeros(512), count=10, exclude=frozenset()
    )

    assert widths(connection.statements) == []


def test_the_width_is_set_once_and_never_lowered() -> None:
    store = PostgresVectorStore(connection := RecordingConnection())

    store.neighbours(np.zeros(512), count=50, exclude=frozenset())
    store.neighbours(np.zeros(512), count=50, exclude=frozenset())
    store.neighbours(np.zeros(512), count=20, exclude=frozenset())

    assert widths(connection.statements) == [100]


def test_a_larger_request_widens_it_further() -> None:
    store = PostgresVectorStore(connection := RecordingConnection())

    store.neighbours(np.zeros(512), count=50, exclude=frozenset())
    store.neighbours(np.zeros(512), count=200, exclude=frozenset())

    assert widths(connection.statements) == [100, 400]
