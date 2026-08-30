"""The pipeline manifest: what has been done, per photograph, per step.

The offline run is tens of thousands of small steps over several hours. It will be
interrupted — by an error, by a machine restart, or deliberately, because proving
that it survives being killed halfway is part of the phase 2 gate. The manifest is
what makes the second run continue instead of start over.

One row per (photograph, step) in ``ingest_status``, created by EF migration
``InitialSchema``. The identifier is the dataset name such as ``a0042-kme_610``
rather than a foreign key to ``photos``: the first steps run before any photo row
exists, so the manifest has to be able to record progress for something the
database does not know about yet.

**The rule that makes all of this work, and the one that is easy to get backwards:
a step is marked done only after its result is durably written.** Object in
storage first, row in the database first, mark afterwards. Reversed, a crash
between the two leaves a step marked finished with the work missing, and every
later run skips it. Nothing fails, no test goes red, and it surfaces only when
somebody counts rows.

The same rule decides where a step *begins and ends*. "Fetch the file", "derive
from it" and "delete the original" are one step, not three: as three, a crash
after the first leaves hundreds of gigabytes on disk that no restart will ever
clean up, because as far as the manifest is concerned the fetch finished.
"""

from collections.abc import Iterable
from enum import StrEnum

import psycopg

# The dataset identifier of a photograph, e.g. "a0042-kme_610".
PhotoReference = str


class Status(StrEnum):
    """Mirrors ``PhotoAssistant.Domain.Enums.JobStatus``.

    Stored as text, and the spelling matters: EF writes the C# enum names, so a
    lower-case value here would produce rows the backend cannot read back into
    its enum. The same reason the backend stores them as text rather than as
    integers — a reordered enum must not be able to reinterpret existing rows.
    """

    PENDING = "Pending"
    RUNNING = "Running"
    DONE = "Done"
    FAILED = "Failed"


# Step names. Free-form text in the schema on purpose: the list belongs to the
# pipeline and grows with every adapter, so it is not worth a migration each time.
STEP_DERIVE_BEFORE = "derive_before"
STEP_EMBED_CONTENT = "embed_content"
STEP_PUBLISH = "publish"


def step_derive_after(expert: str) -> str:
    """Deriving the 512px "after" image for one expert, e.g. ``derive_after:c``."""
    return f"derive_after:{expert}"


def step_fit(expert: str) -> str:
    """Fitting one expert's edit of one photograph, e.g. ``fit:c``."""
    return f"fit:{expert}"


def step_refit(expert: str) -> str:
    """A second, harder search over an edit the first pass fitted poorly.

    Tracked separately from ``fit:`` so that the tail can be revisited without
    the first pass's marks being disturbed, and so that a second pass which is
    interrupted resumes rather than starting over.
    """
    return f"refit:{expert}"


def step_embed_style(expert: str) -> str:
    """Style fingerprint of one expert's result, e.g. ``embed_style:c``."""
    return f"embed_style:{expert}"


class Manifest:
    """Progress tracking over an existing connection.

    Takes a connection rather than a configuration so that the caller decides
    what the marks are part of. On an autocommit connection every mark is durable
    the moment it is made, which is what a step ending in an upload wants. On a
    transactional one the marks land with the caller's commit, which is what a
    step whose result is itself a database row wants — there the mark and the rows
    should be one atomic write.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def claim(self, reference: PhotoReference, step: str) -> bool:
        """Take ownership of one step, returning whether this caller got it.

        A single statement, so two workers racing for the same step cannot both
        win: the conflict clause only promotes a row that is currently pending or
        failed, and the ``RETURNING`` is empty for the loser. That holds across
        processes as well as threads, which plain "read then write" would not.

        A step already ``Done`` is never re-claimed. That is the whole point.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ingest_status (photo_reference, step, status, error, updated_at)
                VALUES (%s, %s, %s, NULL, now())
                ON CONFLICT (photo_reference, step) DO UPDATE
                    SET status = EXCLUDED.status, error = NULL, updated_at = now()
                    WHERE ingest_status.status IN (%s, %s)
                RETURNING photo_reference
                """,
                (reference, step, Status.RUNNING, Status.PENDING, Status.FAILED),
            )
            return cursor.fetchone() is not None

    def complete(self, reference: PhotoReference, step: str) -> None:
        """Mark a step done. Call this **after** the result is durably written."""
        self._set(reference, step, Status.DONE, None)

    def fail(self, reference: PhotoReference, step: str, error: str) -> None:
        """Mark a step failed, keeping why.

        A failed step is claimable again, so a later run retries it. The message
        is kept so that a run ending with forty failures can be read rather than
        guessed at; it is truncated because a stack trace per row would turn the
        manifest into a log.
        """
        self._set(reference, step, Status.FAILED, error[:2000])

    def _set(
        self, reference: PhotoReference, step: str, status: Status, error: str | None
    ) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ingest_status (photo_reference, step, status, error, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (photo_reference, step) DO UPDATE
                    SET status = EXCLUDED.status,
                        error = EXCLUDED.error,
                        updated_at = now()
                """,
                (reference, step, status, error),
            )

    def done_references(self, step: str) -> set[PhotoReference]:
        """Every photograph whose given step is finished.

        One query for the whole step rather than one per photograph. The caller
        holds a list of 5000 names and wants the difference; asking the database
        5000 times for that is a round trip per name and turns a startup check
        into a minute of waiting.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT photo_reference FROM ingest_status WHERE step = %s AND status = %s",
                (step, Status.DONE),
            )
            return {row[0] for row in cursor.fetchall()}

    def pending_from(self, step: str, candidates: Iterable[PhotoReference]) -> list[PhotoReference]:
        """The candidates whose step is not done yet, in the order given.

        Order is preserved because the caller's order is usually deliberate — a
        stratified sample, or a deterministic stride — and a set would throw that
        away.
        """
        done = self.done_references(step)
        return [reference for reference in candidates if reference not in done]

    def reset_stale_running(self, step: str) -> int:
        """Return steps left ``Running`` by a dead process to ``Pending``.

        Necessary because ``claim`` deliberately refuses to take a step that is
        already running: without that refusal two workers would duplicate work,
        but with it, a crash strands its in-flight steps in a state nothing will
        ever pick up. They would be silently skipped for the rest of the project.

        Call this once at startup, from a single process, before any worker
        starts. Calling it while workers are running would hand their steps to
        somebody else.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ingest_status SET status = %s, updated_at = now()
                WHERE step = %s AND status = %s
                """,
                (Status.PENDING, step, Status.RUNNING),
            )
            return cursor.rowcount

    def counts(self, step: str) -> dict[str, int]:
        """How many rows of a step sit in each status. For progress and reports."""
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, count(*) FROM ingest_status WHERE step = %s GROUP BY status",
                (step,),
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
