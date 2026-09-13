"""The pgvector store against the real, populated database.

**Skipped when no database answers**, like the other storage tests: the schema
comes from EF migrations and the rows from the phase 2 pipeline, and a test that
built its own copy of either would be checking a second definition of both.

    docker compose --env-file .env -f infra/docker-compose.yml up -d postgres

Nothing here writes. The interesting test is the last pair: hiding a photograph
must remove its own edits from the pool, **and** not hiding it must put them back.
One without the other proves nothing — a filter that is never reached and a filter
that works look identical from the passing side (§B50).
"""

import os

import numpy as np
import pytest

psycopg = pytest.importorskip("psycopg")

from photoassistant.embeddings.fingerprint import FINGERPRINT_DIMENSION  # noqa: E402
from photoassistant.recommender import PostgresVectorStore  # noqa: E402
from photoassistant.storage.config import ConfigurationError, DatabaseConfig  # noqa: E402

QUERY_PHOTOGRAPH = """
SELECT p.source_reference, p.clip_embedding::text
  FROM photos p
  JOIN examples e ON e.photo_id = p.id AND NOT e.excluded_from_fitting
 WHERE p.clip_embedding IS NOT NULL
 GROUP BY p.source_reference, p.clip_embedding
HAVING count(*) = 5
 ORDER BY p.source_reference
 LIMIT 1
"""


def _configuration() -> DatabaseConfig:
    environ = dict(os.environ)
    environ.setdefault("POSTGRES_HOST", environ.get("POSTGRES_HOST_LOCAL", "localhost"))
    return DatabaseConfig.from_environment(environ)


@pytest.fixture(scope="module")
def connection():
    try:
        config = _configuration()
    except ConfigurationError as error:
        pytest.skip(f"database not configured: {error}")
    try:
        handle = psycopg.connect(config.conninfo, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {config.host}:{config.port} - {error}")

    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture(scope="module")
def store(connection):
    return PostgresVectorStore(connection)


@pytest.fixture(scope="module")
def query(connection):
    """A photograph with all five expert edits, and its own CLIP vector.

    Its own vector is the sharpest possible query: the nearest photograph must be
    itself, at distance zero, which is exactly the situation the held-out set
    exists to prevent.
    """
    with connection.cursor() as cursor:
        cursor.execute(QUERY_PHOTOGRAPH)
        row = cursor.fetchone()
    if row is None:
        pytest.skip("no fully fitted photograph in the database - is this the phase 2 corpus?")

    reference, literal = row
    return reference, np.fromstring(literal.strip("[]"), sep=",")


def test_the_search_returns_the_number_asked_for_nearest_first(store, query):
    _, vector = query

    found = store.neighbours(vector, count=10, exclude=frozenset())

    assert len(found) == 10
    assert [entry.distance for entry in found] == sorted(entry.distance for entry in found)


def test_a_photograph_is_its_own_nearest_neighbour(store, query):
    reference, vector = query

    found = store.neighbours(vector, count=5, exclude=frozenset())

    assert found[0].reference == reference
    assert found[0].distance == pytest.approx(0.0, abs=1e-6)


def test_asking_for_nothing_does_not_query(store, query):
    _, vector = query

    assert store.neighbours(vector, count=0, exclude=frozenset()) == []


def test_the_pool_carries_recipes_fingerprints_and_the_scene_distance(store, query):
    _, vector = query
    found = store.neighbours(vector, count=3, exclude=frozenset())

    pool = store.candidates(found)

    assert pool
    references = {neighbour.reference for neighbour in found}
    distances = {neighbour.reference: neighbour.distance for neighbour in found}
    for entry in pool:
        assert entry.photo_reference in references
        assert entry.photo_distance == pytest.approx(distances[entry.photo_reference])
        assert entry.fingerprint.shape == (FINGERPRINT_DIMENSION,)
        assert entry.recipe.version == 1
    assert pool[0].photo_distance <= pool[-1].photo_distance


def test_an_empty_neighbour_list_yields_an_empty_pool(store):
    assert store.candidates([]) == []


# -- the filter, proven in both directions ------------------------------------


def test_without_the_filter_a_photograph_finds_its_own_edits(store, query):
    """The positive control. If this ever stops holding, the test below is empty."""
    reference, vector = query
    found = store.neighbours(vector, count=5, exclude=frozenset())

    pool = store.candidates(found)

    assert any(entry.photo_reference == reference for entry in pool)


def test_with_the_filter_the_photograph_and_its_edits_are_gone(store, query):
    reference, vector = query

    found = store.neighbours(vector, count=5, exclude=frozenset({reference}))
    pool = store.candidates(found)

    assert all(entry.reference != reference for entry in found)
    assert all(entry.photo_reference != reference for entry in pool)


def test_hiding_one_photograph_still_returns_a_full_set_of_neighbours(store, query):
    """Post-filtering would quietly hand back four where five were asked for."""
    reference, vector = query

    found = store.neighbours(vector, count=5, exclude=frozenset({reference}))

    assert len(found) == 5
