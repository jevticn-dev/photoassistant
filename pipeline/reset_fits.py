"""Discard every fitted recipe, so the next pass starts from the current renderer.

    uv run --project ml python -m pipeline.reset_fits            # what would go
    uv run --project ml python -m pipeline.reset_fits --confirm  # actually go

**Why this exists as a command rather than as two lines of SQL.** A recipe fitted
under one renderer does not mean the same thing under another: the numbers are
whatever reproduced the expert's image *through the formulas of the day*. After a
change like ADR-22 they have to be thrown away and searched for again.

The trap is that throwing away the rows is not enough. The manifest records
``fit:{expert}`` as done, and the fitting pass consults the manifest and nothing
else, so a run after a partial cleanup would **skip** the very edits whose
recipes were deleted. The database would end up holding recipes from two
different renderers — no error, no failing test, and nothing to notice until
somebody compared numbers that no longer belonged together.

So both go, together, in one transaction: the rows and the marks that claim they
exist.

Nothing else is touched. The derivatives in object storage are what the images
look like, not what a recipe means, and the catalogue staging is upstream of both.
"""

import argparse
import sys

from photoassistant.storage import DatabaseConfig, connect

from pipeline.environment import load
from pipeline.fivek.catalogue import EXPERTS


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="perform the deletion. Without it, this only reports what would be deleted.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="what made the recipes stale, e.g. 'ADR-22'. Printed, and kept in the report.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load()

    steps = [f"fit:{expert}" for expert in EXPERTS]

    with connect(DatabaseConfig.from_environment(), autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM examples")
            examples = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM ingest_status WHERE step = ANY(%s)", (steps,)
            )
            marks = cursor.fetchone()[0]

        print(f"fitted recipes in examples: {examples}")
        print(f"fit marks in the manifest:  {marks}")

        if examples == 0 and marks == 0:
            print("\nnothing to discard")
            return

        if not arguments.confirm:
            print("\ndry run. Re-run with --confirm to delete both.")
            print("Deleting one without the other would leave the next pass skipping")
            print("edits whose recipes are gone — a database of two renderers at once.")
            return

        # One transaction. Either both the rows and the marks go, or neither does;
        # the state in between is the one that cannot be detected afterwards.
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM examples")
            cursor.execute("DELETE FROM ingest_status WHERE step = ANY(%s)", (steps,))

        reason = f" ({arguments.reason})" if arguments.reason else ""
        print(f"\ndiscarded {examples} recipes and {marks} manifest marks{reason}")
        print("the derivatives in object storage are untouched; refitting needs no downloads")


if __name__ == "__main__":
    sys.exit(main())
