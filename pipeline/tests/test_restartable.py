"""Killing the embedding pass halfway must cost nothing but the work in flight.

The phase 2 gate asks for this explicitly, and it is the one property of the
pipeline that cannot be checked by reading the code: the manifest, the
transaction boundaries and the unique index only add up to "restartable" when a
real process is really killed between two of its writes.

Two claims, proven separately because they fail differently:

**Resumption** — a second run skips what the first finished. Deterministic: the
first run is given a small limit and allowed to finish, the second a larger one,
and what the second computes is counted.

**Survival of a kill** — a run stopped mid-flight leaves no duplicate row, no row
marked done without its vector, and nothing that a later run refuses to pick up.
The child is killed only after the database shows it has actually written
something, so the test is not a race with process startup.

Runs against the real database and object store, over rows this test creates and
removes. Skipped without them, as in CI.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from photoassistant.storage import (  # noqa: E402
    ConfigurationError,
    DatabaseConfig,
    step_embed_style,
)

from pipeline.embed_all import SCALING_FILE  # noqa: E402
from pipeline.environment import REPOSITORY_ROOT  # noqa: E402

# Where the child writes its report instead of over the committed one.
TEST_REPORT_NAME = "test_embed_report.json"


def _configuration() -> DatabaseConfig:
    environ = dict(os.environ)
    environ.setdefault("POSTGRES_HOST", environ.get("POSTGRES_HOST_LOCAL", "localhost"))
    return DatabaseConfig.from_environment(environ)


def _connect():
    try:
        config = _configuration()
    except ConfigurationError as error:
        pytest.skip(f"database not configured: {error}")
    try:
        return psycopg.connect(config.conninfo, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {config.host}:{config.port} — {error}")


def _require_object_store() -> None:
    """Skip rather than fail when the object store is absent.

    The pass under test reads both images out of storage, so without it every
    edit fails and the suite goes red for a reason that has nothing to do with
    restartability. The database already skipped for that reason; the store did
    not, and a run with Postgres up and MinIO down reported two failures that
    looked like defects.

    ``exists`` on a key that is not there is the cheapest probe that still crosses
    the network: a missing object answers False, an absent endpoint raises.
    """
    from photoassistant.storage import ObjectStorageConfig, ObjectStore

    try:
        store = ObjectStore(ObjectStorageConfig.from_environment())
    except ConfigurationError as error:
        pytest.skip(f"object storage not configured: {error}")

    try:
        store.exists(store.derivatives, "probe-that-does-not-exist")
    except Exception as error:  # noqa: BLE001 - any failure here means "not reachable"
        pytest.skip(f"no object storage — {error}")


@pytest.fixture
def corpus():
    """Five photographs with one fitted example each, removed afterwards.

    Their references carry a ``restart-test-`` prefix so that everything this test
    touches can be found and deleted by name, and so that a failed run leaves an
    obvious trail rather than five anonymous rows among twenty-five thousand.
    """
    if not SCALING_FILE.is_file():
        pytest.skip(f"{SCALING_FILE} missing — run pipeline.embed_all --calibrate first")

    _require_object_store()
    connection = _connect()
    prefix = f"restart-test-{uuid.uuid4().hex[:8]}"
    references = [f"{prefix}-{index}" for index in range(5)]

    # Real derivatives, borrowed rather than uploaded: the point of the test is
    # the manifest and the writes, not image decoding, and pointing at keys that
    # already exist keeps it from depending on an upload of its own.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_reference FROM photos WHERE source = 'Fivek' "
            "AND pre512_key IS NOT NULL ORDER BY source_reference LIMIT 1"
        )
        row = cursor.fetchone()
        if row is None:
            pytest.skip("no ingested photographs to borrow derivatives from")
        donor = row[0]

        for reference in references:
            photo_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO photos (id, source, pre512_key, proxy2048_key,
                                    source_reference, created_at)
                VALUES (%s, 'Fivek', %s, %s, %s, now())
                """,
                (
                    photo_id,
                    f"fivek/{donor}/pre512.png",
                    f"fivek/{donor}/proxy2048.jpg",
                    reference,
                ),
            )
            cursor.execute(
                """
                INSERT INTO examples (id, photo_id, edit, expert, fit_error, after_key,
                                      excluded_from_fitting, created_at)
                VALUES (%s, %s, %s, 'c', 1.5, %s, false, now())
                """,
                (
                    str(uuid.uuid4()),
                    photo_id,
                    json.dumps({"schema": 1, "tone": {"exposure": 0.4, "contrast": 12.0}}),
                    f"fivek/{donor}/after512-c.png",
                ),
            )

    yield connection, references

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM ingest_status WHERE photo_reference LIKE %s", (f"{prefix}%",))
        cursor.execute(
            "DELETE FROM examples WHERE photo_id IN "
            "(SELECT id FROM photos WHERE source_reference LIKE %s)",
            (f"{prefix}%",),
        )
        cursor.execute("DELETE FROM photos WHERE source_reference LIKE %s", (f"{prefix}%",))
    connection.close()


def _environment() -> dict[str, str]:
    """The child's environment, with its report pointed away from the real one.

    ``pipeline/embed_report.json`` is a committed measurement. Left alone, every
    run of this test overwrites it with five fixture rows — a file that looks like
    a measurement and describes a fixture.
    """
    redirected = Path(REPOSITORY_ROOT) / "pipeline" / ".work" / TEST_REPORT_NAME
    return {**os.environ, "EMBED_REPORT": str(redirected)}


def run_style(limit: int, references: list[str]) -> subprocess.CompletedProcess:
    """One ``--style`` pass restricted to this test's rows."""
    return subprocess.run(
        [
            sys.executable, "-m", "pipeline.embed_all", "--style",
            "--limit", str(limit), "--only", ",".join(references),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env=_environment(),
    )


def state(connection, references: list[str]) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*), count(e.style_fingerprint), count(DISTINCT (e.photo_id, e.expert))
              FROM examples e JOIN photos p ON p.id = e.photo_id
             WHERE p.source_reference = ANY(%s)
            """,
            (references,),
        )
        rows, fingerprints, distinct_pairs = cursor.fetchone()

        cursor.execute(
            "SELECT count(*) FROM ingest_status WHERE photo_reference = ANY(%s) "
            "AND step = %s AND status = 'Done'",
            (references, step_embed_style("c")),
        )
        return {
            "rows": rows,
            "fingerprints": fingerprints,
            "distinct_pairs": distinct_pairs,
            "done": cursor.fetchone()[0],
        }


def test_a_second_run_skips_what_the_first_finished(corpus) -> None:
    connection, references = corpus

    first = run_style(2, references)
    assert first.returncode == 0, first.stderr
    after_first = state(connection, references)
    assert after_first["fingerprints"] == 2
    assert after_first["done"] == 2

    second = run_style(5, references)
    assert second.returncode == 0, second.stderr
    after_second = state(connection, references)

    assert after_second["fingerprints"] == 5
    assert after_second["done"] == 5
    # The claim that matters: the rows were updated, not added beside.
    assert after_second["rows"] == 5
    assert after_second["distinct_pairs"] == 5
    assert "fingerprints to compute 3" in second.stdout


def test_killing_the_run_halfway_leaves_nothing_to_clean_up(corpus) -> None:
    connection, references = corpus

    child = subprocess.Popen(
        [
            sys.executable, "-m", "pipeline.embed_all", "--style",
            "--limit", "5", "--only", ",".join(references),
        ],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_environment(),
    )
    try:
        # Killed only once the database shows real progress. Killing on a timer
        # would make this a race with interpreter startup, and a test that
        # sometimes kills nothing would pass while proving nothing.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if state(connection, references)["fingerprints"] >= 1:
                break
            if child.poll() is not None:
                pytest.skip("the run finished before it could be interrupted")
            time.sleep(0.2)
        else:
            pytest.skip("no progress within the timeout; nothing was interrupted")
    finally:
        child.kill()
        child.wait(timeout=30)

    interrupted = state(connection, references)
    assert interrupted["rows"] == 5
    assert interrupted["distinct_pairs"] == 5
    # A step is marked done only after its vector is written, never before, so
    # the marks can never run ahead of the work (notes §B18).
    assert interrupted["done"] <= interrupted["fingerprints"]

    resumed = run_style(5, references)
    assert resumed.returncode == 0, resumed.stderr
    after = state(connection, references)

    assert after["fingerprints"] == 5
    assert after["done"] == 5
    assert after["rows"] == 5
    assert after["distinct_pairs"] == 5
    assert after["done"] >= interrupted["done"]


def test_no_temporary_files_are_left_behind(corpus) -> None:
    """The embedding pass streams from object storage and writes nothing to disk.

    Stated as a test because the fetch step *does* write temporary files, and a
    future change that gives this pass a cache would otherwise inherit the
    fetcher's problem — hundreds of gigabytes that no restart cleans up — without
    anybody noticing.
    """
    _, references = corpus
    work = Path(REPOSITORY_ROOT) / "pipeline" / ".work"
    # The redirected report is this test's own file, not something the pass left.
    ignored = {TEST_REPORT_NAME}
    before = {path.name for path in work.glob("*")} - ignored if work.is_dir() else set()

    assert run_style(5, references).returncode == 0

    after = {path.name for path in work.glob("*")} - ignored if work.is_dir() else set()
    assert after == before
