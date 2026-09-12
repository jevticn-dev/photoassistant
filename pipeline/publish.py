"""Finish the tables and prove they are finished (phase 2, tasks 9 and 10).

    uv run --project ml python -m pipeline.publish --verify
    uv run --project ml python -m pipeline.publish --confirm

Two jobs that belong together because the second checks the first.

**Insert the edits that could not be fitted.** Nineteen of the 25.000 use grayscale
conversion, local adjustments, a crop or a rotation, none of which edit schema v1
models. ``fit_all`` skips them, so without this the table would hold 24.981 rows
and quietly claim that is all there ever was. They belong in the database as what
they are: evidence that exists, marked as unusable for fitting, with the reason
kept.

``edit`` holds the **analytic translation** of the catalogue's own parameters. The
column cannot be null and inventing a neutral recipe would be worse — it would
read as "the expert did nothing". The translation is what the catalogue says,
untested against the image; ``excluded_from_fitting`` and a null ``fit_error`` are
what say so.

**Mark each photograph published once it is genuinely complete.** Not a formality:
the phase gate asks for ``count(*) from ingest_status where status <> 'Done'``, and
that number only means something if the ``publish`` step actually checked
something. Here it checks that the photograph has its row, its CLIP embedding, all
five of its edits, and a fingerprint on each fitted one.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from photoassistant.storage import (
    STEP_PUBLISH,
    DatabaseConfig,
    Manifest,
    connect,
)

from pipeline.environment import REPOSITORY_ROOT, load

# Overridable for the same reason as in embed_all: a test run must not overwrite
# a committed measurement.
REPORT = Path(os.environ.get("PUBLISH_REPORT") or Path(__file__).parent / "publish_report.json")

EXPECTED_PHOTOS = 5000
EXPECTED_EXAMPLES = 25000


def staging_dir() -> Path:
    return Path(os.environ.get("STAGING_DIR", REPOSITORY_ROOT / "pipeline/.work/staging"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"staging file missing: {path}. Run pipeline.parse_catalogue first.")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def photo_ids(connection) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT source_reference, id FROM photos WHERE source = 'Fivek'")
        return {reference: str(identifier) for reference, identifier in cursor.fetchall()}


def insert_excluded(connection, rows: list[dict], identifiers: dict[str, str]) -> int:
    """Write the unfittable edits, once. Safe to run again.

    Idempotent through the unique index on (photo_id, expert) rather than through
    a prior check: a check and an insert are two statements, and the whole reason
    the index exists is that a second writer must not be able to duplicate a row
    even if it forgets to look first (notes §B47).

    The ``WHERE expert IS NOT NULL`` is not decoration. That index is partial, and
    Postgres matches an ``ON CONFLICT`` target against the index **including its
    predicate**; without the repeated condition it finds no matching constraint
    and refuses the statement outright. ``ensure_photo_rows`` in ``fit_all`` spells
    it out for the same reason.
    """
    written = 0
    with connection.transaction(), connection.cursor() as cursor:
        for row in rows:
            identifier = identifiers.get(row["reference"])
            if identifier is None:
                raise RuntimeError(f"no photos row for {row['reference']}")

            cursor.execute(
                """
                INSERT INTO examples (id, photo_id, edit, expert, fit_error, after_key,
                                      excluded_from_fitting, excluded_reason, created_at)
                VALUES (%s, %s, %s, %s, NULL, %s, true, %s, now())
                ON CONFLICT (photo_id, expert) WHERE expert IS NOT NULL DO UPDATE
                    SET excluded_from_fitting = true,
                        excluded_reason = EXCLUDED.excluded_reason
                """,
                (
                    str(uuid.uuid4()),
                    identifier,
                    json.dumps(row["analytic"]),
                    row["expert"],
                    f"fivek/{row['reference']}/after512-{row['expert']}.png",
                    row["excluded_reason"],
                ),
            )
            written += cursor.rowcount
    return written


def incomplete(connection) -> list[dict]:
    """Photographs that are not fully ingested, and what each is missing.

    One query rather than five thousand: the pipeline has to be able to say "all
    of them are done" without a round trip per photograph.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.source_reference,
                   (p.clip_embedding IS NULL) AS no_embedding,
                   count(e.id) AS examples,
                   count(*) FILTER (
                       WHERE NOT e.excluded_from_fitting AND e.style_fingerprint IS NULL
                   ) AS missing_fingerprints
              FROM photos p
              LEFT JOIN examples e ON e.photo_id = p.id
             WHERE p.source = 'Fivek'
             GROUP BY p.source_reference, p.clip_embedding IS NULL
            HAVING (p.clip_embedding IS NULL)
                OR count(e.id) <> 5
                OR count(*) FILTER (
                       WHERE NOT e.excluded_from_fitting AND e.style_fingerprint IS NULL
                   ) > 0
             ORDER BY p.source_reference
            """
        )
        return [
            {
                "reference": reference,
                "no_embedding": no_embedding,
                "examples": examples,
                "missing_fingerprints": missing,
            }
            for reference, no_embedding, examples, missing in cursor.fetchall()
        ]


def mark_complete(connection, references: list[str]) -> int:
    tracker = Manifest(connection)
    already = tracker.done_references(STEP_PUBLISH)
    marked = 0
    for reference in references:
        if reference in already:
            continue
        tracker.complete(reference, STEP_PUBLISH)
        marked += 1
    return marked


def gate_queries(connection) -> dict:
    """The numbers the phase gate asks for, verbatim, so the report can quote them."""
    statements = {
        "photos": "SELECT count(*) FROM photos",
        "examples": "SELECT count(*) FROM examples",
        "excluded": "SELECT count(*) FROM examples WHERE excluded_from_fitting",
        "with_embedding": "SELECT count(*) FROM photos WHERE clip_embedding IS NOT NULL",
        "with_fingerprint": "SELECT count(*) FROM examples WHERE style_fingerprint IS NOT NULL",
        "manifest_not_done": "SELECT count(*) FROM ingest_status WHERE status <> 'Done'",
    }

    results: dict = {}
    with connection.cursor() as cursor:
        for name, statement in statements.items():
            cursor.execute(statement)
            results[name] = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT excluded_reason, count(*) FROM examples
             WHERE excluded_from_fitting GROUP BY excluded_reason ORDER BY excluded_reason
            """
        )
        results["excluded_reasons"] = dict(cursor.fetchall())

        cursor.execute(
            """
            SELECT round(avg(fit_error)::numeric, 4),
                   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY fit_error)::numeric, 4),
                   round(percentile_cont(0.9) WITHIN GROUP (ORDER BY fit_error)::numeric, 4),
                   round(max(fit_error)::numeric, 4)
              FROM examples WHERE NOT excluded_from_fitting
            """
        )
        mean, median, p90, worst = cursor.fetchone()
        results["fit_error"] = {
            "mean": float(mean) if mean is not None else None,
            "median": float(median) if median is not None else None,
            "p90": float(p90) if p90 is not None else None,
            "max": float(worst) if worst is not None else None,
        }

        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'photos' ORDER BY 1")
        results["photo_indexes"] = [row[0] for row in cursor.fetchall()]

    return results


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true",
                        help="write the excluded rows and mark completed photographs")
    parser.add_argument("--verify", action="store_true", help="only read and report")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load()

    if not (arguments.confirm or arguments.verify):
        sys.exit("pass --verify to inspect, or --confirm to write")

    edits = read_jsonl(staging_dir() / "edits.jsonl")
    excluded = [edit for edit in edits if edit.get("excluded_reason")]
    print(f"excluded edits in staging: {len(excluded)}")

    database = DatabaseConfig.from_environment()

    if arguments.confirm:
        with connect(database, autocommit=False) as connection:
            written = insert_excluded(connection, excluded, photo_ids(connection))
            connection.commit()
        print(f"excluded rows written or refreshed: {written}")

    with connect(database) as connection:
        missing = incomplete(connection)
        print(f"photographs not fully ingested: {len(missing)}")
        for row in missing[:10]:
            print(f"  {row}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")

        if arguments.confirm:
            complete = [
                reference
                for reference in photo_ids(connection)
                if reference not in {row["reference"] for row in missing}
            ]
            marked = mark_complete(connection, complete)
            print(f"photographs marked published: {marked}")

        results = gate_queries(connection)

    print("\n" + json.dumps(results, indent=2))

    problems = []
    if results["photos"] != EXPECTED_PHOTOS:
        problems.append(f"photos is {results['photos']}, expected {EXPECTED_PHOTOS}")
    if results["examples"] != EXPECTED_EXAMPLES:
        problems.append(f"examples is {results['examples']}, expected {EXPECTED_EXAMPLES}")
    if missing:
        problems.append(f"{len(missing)} photographs incomplete")

    REPORT.write_text(
        json.dumps({**results, "incomplete": missing, "problems": problems}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nreport: {REPORT}")

    if problems:
        print("\nNOT READY:")
        for problem in problems:
            print(f"  - {problem}")


if __name__ == "__main__":
    main()
