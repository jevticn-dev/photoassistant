"""Drawing the evaluation split, and noticing when it has gone stale.

Two halves. The drawing and the staleness check are pure functions over a list of
references and are tested as such. What counts as *eligible* is a claim about the
real corpus — that every photograph in the split has at least two fitted examples
— and can only be checked against the migrated database, so that part skips when
no Postgres answers, as in CI.
"""

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from photoassistant.recommender import HELD_OUT_COUNT, EvaluationSplit  # noqa: E402
from photoassistant.storage import ConfigurationError, DatabaseConfig  # noqa: E402

from pipeline.make_split import (  # noqa: E402
    MINIMUM_FITTED_EXAMPLES,
    draw,
    eligible_references,
    verify,
)

REFERENCES = [f"a{index:04d}" for index in range(1, 1001)]


def _connect():
    environ = dict(os.environ)
    environ.setdefault("POSTGRES_HOST", environ.get("POSTGRES_HOST_LOCAL", "localhost"))
    try:
        config = DatabaseConfig.from_environment(environ)
    except ConfigurationError as error:
        pytest.skip(f"database not configured: {error}")
    try:
        return psycopg.connect(config.conninfo, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as error:
        pytest.skip(f"no database at {config.host}:{config.port} — {error}")


@pytest.fixture(scope="module")
def connection():
    handle = _connect()
    try:
        yield handle
    finally:
        handle.close()


# -- drawing ------------------------------------------------------------------


def test_the_same_seed_draws_the_same_photographs():
    assert draw(REFERENCES, 7, 50).held_out == draw(REFERENCES, 7, 50).held_out


def test_a_different_seed_draws_a_different_sample():
    """Not a law of probability — a check that the seed is actually used.

    Two draws of 50 from 1.000 agreeing completely has probability around
    10^-100, so an equal result means the seed was ignored, which is exactly the
    kind of silently-inert parameter phase 2 was bitten by (notes §B50).
    """
    assert draw(REFERENCES, 7, 50).held_out != draw(REFERENCES, 8, 50).held_out


def test_the_sample_is_sorted_and_free_of_duplicates():
    held_out = draw(REFERENCES, 1, 100).held_out
    assert list(held_out) == sorted(held_out)
    assert len(set(held_out)) == 100


def test_everything_drawn_comes_from_the_candidates():
    assert set(draw(REFERENCES, 3, 100).held_out) <= set(REFERENCES)


def test_the_split_records_how_many_it_drew_from():
    assert draw(REFERENCES, 3, 100).drawn_from == len(REFERENCES)


def test_drawing_more_than_there_is_exits_rather_than_returning_a_short_split():
    with pytest.raises(SystemExit, match="only 10 eligible"):
        draw(REFERENCES[:10], 1, 500)


# -- staleness ----------------------------------------------------------------


def fixed(held_out, drawn_from=None) -> EvaluationSplit:
    return EvaluationSplit(
        seed=1,
        created_at="2026-09-13T12:00:00+00:00",
        drawn_from=len(REFERENCES) if drawn_from is None else drawn_from,
        held_out=tuple(held_out),
    )


def test_a_matching_split_reports_no_problems():
    split = draw(REFERENCES, 1, HELD_OUT_COUNT)
    assert verify(split, REFERENCES) == []


def test_a_reference_that_stopped_being_eligible_is_reported():
    split = draw(REFERENCES, 1, HELD_OUT_COUNT)
    shrunk = [reference for reference in REFERENCES if reference != split.held_out[0]]

    problems = verify(split, shrunk)
    assert any("no longer eligible" in problem for problem in problems)


def test_a_corpus_that_changed_size_is_reported():
    """The complement is the build set, so a corpus of another size is another experiment."""
    split = draw(REFERENCES, 1, HELD_OUT_COUNT)

    problems = verify(split, REFERENCES + ["a1001"])
    assert any("no longer the one that was measured" in problem for problem in problems)


def test_a_split_of_the_wrong_size_is_reported():
    problems = verify(fixed(REFERENCES[:10]), REFERENCES)
    assert any(f"expected {HELD_OUT_COUNT}" in problem for problem in problems)


# -- against the real corpus --------------------------------------------------


def test_every_eligible_photograph_really_has_two_fitted_examples(connection):
    references = eligible_references(connection)
    assert references, "no eligible photographs — is this the migrated database?"

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
              FROM (
                SELECT p.source_reference
                  FROM photos p
                  JOIN examples e ON e.photo_id = p.id AND NOT e.excluded_from_fitting
                 WHERE p.source_reference = ANY(%s)
                 GROUP BY p.source_reference
                HAVING count(*) < %s
              ) s
            """,
            (references, MINIMUM_FITTED_EXAMPLES),
        )
        (too_few,) = cursor.fetchone()

    assert too_few == 0


def test_ineligible_photographs_are_left_out_but_still_in_the_database(connection):
    """The three all-excluded photographs cannot be questions, and are still answers."""
    eligible = set(eligible_references(connection))

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.source_reference
              FROM photos p
              LEFT JOIN examples e ON e.photo_id = p.id AND NOT e.excluded_from_fitting
             WHERE p.source = 'Fivek'
             GROUP BY p.source_reference
            HAVING count(e.id) < %s
            """,
            (MINIMUM_FITTED_EXAMPLES,),
        )
        ineligible = {reference for (reference,) in cursor.fetchall()}

        cursor.execute(
            "SELECT count(*) FROM photos WHERE source_reference = ANY(%s)",
            (list(ineligible),),
        )
        (still_present,) = cursor.fetchone()

    assert ineligible, "expected the three photographs whose every edit was excluded"
    assert not (ineligible & eligible)
    assert still_present == len(ineligible)


def test_the_eligible_list_is_ordered_and_unique(connection):
    references = eligible_references(connection)
    assert list(references) == sorted(references)
    assert len(set(references)) == len(references)
