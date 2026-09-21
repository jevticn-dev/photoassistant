"""The ``jobs`` table, from the worker's side.

The queue is a table rather than a broker (ADR-7). The .NET API inserts a row,
this side takes it, and the frontend asks the API for its status. Nothing here
knows about users or projects: a job carries what the work needs, and who was
allowed to ask for it was settled before the row existed.

**The table belongs to the backend.** Its shape comes from EF migrations; this
module only reads and writes rows, exactly as the rest of ``storage`` does.

The status values are the C# enum names as EF stores them — ``Pending``,
``Running``, ``Done``, ``Failed`` — and the type is ``Export``. They are written
out as literals here rather than derived, because the two sides agree on a
spelling in the database and neither generates it for the other.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg

PENDING = "Pending"
RUNNING = "Running"
DONE = "Done"
FAILED = "Failed"

EXPORT = "Export"


@dataclass(frozen=True)
class ClaimedJob:
    """A job this worker has taken and is now responsible for finishing."""

    id: str
    payload: dict[str, Any]


def claim_next(
    connection: psycopg.Connection,
    *,
    job_type: str = EXPORT,
) -> ClaimedJob | None:
    """Take the oldest pending job of this type, or return None if there is none.

    **One statement, because two would be a race.** Selecting a row and then
    updating it lets a second worker select the same row in between.
    ``FOR UPDATE SKIP LOCKED`` inside the subquery locks the row being taken and
    steps over rows another worker already holds, so two workers take two
    different jobs rather than both taking the first one.

    There is one worker today. The clause costs nothing and is the difference
    between "runs correctly with one worker" and "runs correctly", which is not a
    property to leave until it is needed.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            update jobs
               set status = %s, updated_at = now()
             where id = (
                   select id
                     from jobs
                    where status = %s and type = %s
                    order by created_at
                      for update skip locked
                    limit 1
             )
            returning id, payload
            """,
            (RUNNING, PENDING, job_type),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    identifier, payload = row

    # psycopg gives a jsonb column back as the parsed value already; a string
    # would mean the column is text, which would be a schema change worth
    # noticing rather than working around.
    if not isinstance(payload, dict):
        raise TypeError(f"job {identifier} has a payload that is not an object: {type(payload)}")

    return ClaimedJob(id=str(identifier), payload=payload)


def mark_done(connection: psycopg.Connection, job_id: str, result: dict[str, Any]) -> None:
    """Record the output and close the job."""
    with connection.cursor() as cursor:
        cursor.execute(
            "update jobs set status = %s, result = %s, error = null, updated_at = now()"
            " where id = %s",
            (DONE, json.dumps(result), job_id),
        )


def mark_failed(connection: psycopg.Connection, job_id: str, error: str) -> None:
    """Close the job as failed, with something a person can act on.

    The message is stored because the alternative is a job that says only that it
    did not work. It is the worker's own description — not a traceback, which
    describes our insides and would end up on someone's screen.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "update jobs set status = %s, error = %s, updated_at = now() where id = %s",
            (FAILED, error[:2000], job_id),
        )


def reclaim_stale(
    connection: psycopg.Connection,
    *,
    older_than: timedelta,
    job_type: str = EXPORT,
) -> int:
    """Put jobs that were running before this process started back in the queue.

    A worker that is killed mid-render leaves a row saying ``Running`` that
    nothing is running. Without this it stays that way for good, and the person
    watching the screen waits for something that died — the failure mode phase 2
    made a point of proving against by killing processes on purpose.

    Called at startup, where "older than a few minutes" cannot mean "somebody
    else is working on it": this is the only worker, and it has just begun.
    Returns how many were reclaimed, so a restart that finds some can say so.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "update jobs set status = %s, updated_at = now()"
            " where status = %s and type = %s and updated_at < now() - %s",
            (PENDING, RUNNING, job_type, older_than),
        )

        return cursor.rowcount
