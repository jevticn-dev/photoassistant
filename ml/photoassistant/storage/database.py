"""Connections to the Postgres the backend owns.

**This side never creates a table.** The schema comes from EF migrations in
``backend/src/PhotoAssistant.Infrastructure/Persistence/Migrations``; the pipeline
and the ML service insert into a shape that already exists. Two places issuing
DDL against one database is how a schema ends up with no owner.

Nothing here pools connections. The offline pipeline opens one per worker and
keeps it for the run, and the service is not yet touching the database at all —
when it does, a pool belongs there rather than here, because its lifetime is the
process and the library does not own the process.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from photoassistant.storage.config import DatabaseConfig


def connect(config: DatabaseConfig, *, autocommit: bool = True) -> psycopg.Connection:
    """Open one connection.

    ``autocommit`` defaults to **on**, which is the right setting for the manifest
    and the wrong one almost everywhere else. The manifest exists to survive a
    crash, so each mark has to be durable the moment it is made; inside an open
    transaction a mark would be lost by exactly the failure it is there to record.

    Work that writes rows and marks a step in one breath wants the opposite —
    ``autocommit=False``, both statements in one transaction, so a crash cannot
    leave the mark without the rows.
    """
    return psycopg.connect(config.conninfo, autocommit=autocommit)


@contextmanager
def connection(config: DatabaseConfig, *, autocommit: bool = True) -> Iterator[psycopg.Connection]:
    """``connect`` as a context manager, closing the connection on the way out."""
    handle = connect(config, autocommit=autocommit)
    try:
        yield handle
    finally:
        handle.close()
