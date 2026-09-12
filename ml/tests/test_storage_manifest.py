"""The manifest against a real Postgres.

**Skipped when no database is reachable**, and that is deliberate rather than
convenient. The table is created by an EF migration the backend owns, so a test
that built its own copy would be testing a second definition of the schema and
would stay green while the two drifted apart. Testing against the migrated table
is the only version of this test worth having, and it costs a running container.

    docker compose --env-file .env -f infra/docker-compose.yml up -d postgres

Rows are written under a reference no dataset uses and removed afterwards, so the
test can run against the same database the pipeline fills without disturbing it.
"""

import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from photoassistant.storage.config import ConfigurationError, DatabaseConfig  # noqa: E402
from photoassistant.storage.manifest import Manifest, Status  # noqa: E402

STEP = "test_step"


def _configuration() -> DatabaseConfig:
    """Database settings, filled in from .env's host-side names when unset.

    The library reads container-side names; a developer running pytest has the
    ``*_LOCAL`` ones in .env. Rather than depend on the pipeline's loader from a
    library test, the two names it actually needs are resolved here.
    """
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
        pytest.skip(f"no database at {config.host}:{config.port} — {error}")

    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture
def manifest(connection):
    """A manifest plus a reference unique to this test, cleaned up afterwards."""
    reference = f"test-{uuid.uuid4().hex[:12]}"
    yield Manifest(connection), reference
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM ingest_status WHERE photo_reference = %s", (reference,))


def test_claiming_an_unknown_step_succeeds_and_creates_the_row(manifest):
    tracker, reference = manifest

    assert tracker.claim(reference, STEP) is True
    assert tracker.counts(STEP).get(Status.RUNNING, 0) >= 1


def test_a_running_step_cannot_be_claimed_twice(manifest):
    """Two workers must not both take the same file.

    The refusal is what makes a second process safe. It is also why crashed runs
    need reset_stale_running: the same refusal would otherwise strand whatever
    was in flight.
    """
    tracker, reference = manifest
    assert tracker.claim(reference, STEP) is True

    assert tracker.claim(reference, STEP) is False


def test_a_done_step_is_never_claimed_again(manifest):
    """The whole point of the manifest: a restart skips finished work."""
    tracker, reference = manifest
    tracker.claim(reference, STEP)
    tracker.complete(reference, STEP)

    assert tracker.claim(reference, STEP) is False
    assert reference in tracker.done_references(STEP)


def test_a_failed_step_is_retried_and_its_reason_is_kept(manifest, connection):
    tracker, reference = manifest
    tracker.claim(reference, STEP)
    tracker.fail(reference, STEP, "connection reset by peer")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, error FROM ingest_status WHERE photo_reference = %s AND step = %s",
            (reference, STEP),
        )
        status, error = cursor.fetchone()

    assert status == Status.FAILED
    assert error == "connection reset by peer"
    assert tracker.claim(reference, STEP) is True


def test_completing_clears_an_earlier_failure(manifest, connection):
    """A row that succeeded on retry must not still carry the old reason."""
    tracker, reference = manifest
    tracker.claim(reference, STEP)
    tracker.fail(reference, STEP, "temporary")
    tracker.claim(reference, STEP)
    tracker.complete(reference, STEP)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status, error FROM ingest_status WHERE photo_reference = %s AND step = %s",
            (reference, STEP),
        )
        status, error = cursor.fetchone()

    assert status == Status.DONE
    assert error is None


def test_stale_running_rows_are_returned_to_pending(manifest):
    """Recovery from a crash: what was in flight becomes claimable again."""
    tracker, reference = manifest
    tracker.claim(reference, STEP)

    reset = tracker.reset_stale_running(STEP)

    assert reset >= 1
    assert tracker.claim(reference, STEP) is True


def test_pending_from_keeps_the_callers_order(manifest):
    """Order is usually deliberate — a stratified sample or a fixed stride."""
    tracker, reference = manifest
    tracker.claim(reference, STEP)
    tracker.complete(reference, STEP)

    candidates = ["z-not-done", reference, "a-not-done"]

    assert tracker.pending_from(STEP, candidates) == ["z-not-done", "a-not-done"]


def test_status_values_match_the_spelling_the_backend_writes(manifest, connection):
    """EF writes the C# enum names.

    A lower-case value here would produce rows the backend cannot read back into
    JobStatus, and nothing on this side would notice.
    """
    tracker, reference = manifest
    tracker.claim(reference, STEP)
    tracker.complete(reference, STEP)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM ingest_status WHERE photo_reference = %s AND step = %s",
            (reference, STEP),
        )
        assert cursor.fetchone()[0] == "Done"
