"""The guarantee the second pass rests on: it can only improve a recipe.

Against a real database, because the guarantee is enforced by the ``WHERE`` clause
of an ``UPDATE`` rather than by a comparison in Python. A test over a mock would
be checking the comparison somebody could have written, not the one that runs.

Skipped without a database, as in CI.
"""

import json
import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from photoassistant.storage import (  # noqa: E402
    ConfigurationError,
    DatabaseConfig,
    step_refit,
)

from pipeline.refit_worst import improve  # noqa: E402


def _configuration() -> DatabaseConfig:
    environ = dict(os.environ)
    environ.setdefault("POSTGRES_HOST", environ.get("POSTGRES_HOST_LOCAL", "localhost"))
    return DatabaseConfig.from_environment(environ)


@pytest.fixture
def example():
    """One photograph and one example row of our own, removed afterwards."""
    try:
        config = _configuration()
    except ConfigurationError as error:
        pytest.skip(f"database not configured: {error}")

    try:
        connection = psycopg.connect(config.conninfo, autocommit=False, connect_timeout=5)
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {config.host}:{config.port} — {error}")

    reference = f"test-{uuid.uuid4().hex[:12]}"
    photo_id, example_id = str(uuid.uuid4()), str(uuid.uuid4())
    recipe = {"schema": 1, "tone": {"exposure": 0.5}}

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO photos (id, source, source_reference, created_at)
            VALUES (%s, 'Fivek', %s, now())
            """,
            (photo_id, reference),
        )
        cursor.execute(
            """
            INSERT INTO examples (id, photo_id, edit, expert, fit_error,
                                  excluded_from_fitting, created_at)
            VALUES (%s, %s, %s, 'c', 4.0, false, now())
            """,
            (example_id, photo_id, json.dumps(recipe)),
        )

    row = {"reference": reference, "expert": "c", "fit_error": 4.0, "id": example_id}
    try:
        yield connection, row
    finally:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM examples WHERE id = %s", (example_id,))
            cursor.execute("DELETE FROM photos WHERE id = %s", (photo_id,))
            cursor.execute(
                "DELETE FROM ingest_status WHERE photo_reference = %s", (reference,)
            )
        connection.close()


def stored(connection, example_id: str) -> tuple[float, dict]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT fit_error, edit FROM examples WHERE id = %s", (example_id,))
        error, edit = cursor.fetchone()
    return error, edit if isinstance(edit, dict) else json.loads(edit)


def result_with(error: float) -> dict:
    return {
        "reference": "unused",
        "expert": "c",
        "mean_delta_e": error,
        "edit": {"schema": 1, "tone": {"exposure": 1.25}},
    }


def test_a_better_fit_replaces_the_recipe(example):
    connection, row = example

    assert improve(connection, row, result_with(3.0)) is True

    error, edit = stored(connection, row["id"])
    assert error == pytest.approx(3.0)
    assert edit["tone"]["exposure"] == pytest.approx(1.25)


def test_a_worse_fit_changes_nothing(example):
    """The whole point: a second pass must never be able to make things worse."""
    connection, row = example

    assert improve(connection, row, result_with(5.0)) is False

    error, edit = stored(connection, row["id"])
    assert error == pytest.approx(4.0)
    assert edit["tone"]["exposure"] == pytest.approx(0.5)


def test_an_equal_fit_changes_nothing(example):
    """Strictly better, so a tie leaves the recipe that is already there."""
    connection, row = example

    assert improve(connection, row, result_with(4.0)) is False
    assert stored(connection, row["id"])[0] == pytest.approx(4.0)


def test_the_comparison_uses_the_stored_value_not_the_selected_one(example):
    """Guards against a restart undoing an improvement that already landed.

    Selection reads the error once; by the time a result comes back, another pass
    may have improved that row. Comparing against the value read at selection time
    would then overwrite a better recipe with a worse one.
    """
    connection, row = example
    improve(connection, row, result_with(2.0))

    # `row` still carries the error as it was at selection: 4.0.
    assert improve(connection, row, result_with(3.0)) is False
    assert stored(connection, row["id"])[0] == pytest.approx(2.0)


def test_the_step_is_marked_whether_or_not_the_recipe_changed(example):
    """The work was done either way, so a resumed pass must not repeat it."""
    connection, row = example
    improve(connection, row, result_with(9.0))

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT status FROM ingest_status WHERE photo_reference = %s AND step = %s",
            (row["reference"], step_refit("c")),
        )
        assert cursor.fetchone()[0] == "Done"
