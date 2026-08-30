"""Search harder over the edits the first pass fitted worst (phase 2, task 7).

    uv run --project ml python -m pipeline.refit_worst              # what it would do
    uv run --project ml python -m pipeline.refit_worst --confirm
    uv run --project ml python -m pipeline.refit_worst --confirm --fraction 0.1

The first pass searches from three starting points, which is the right trade over
25.000 edits. Measured over the fifty hardest, six neutral offsets instead of two
improve the mean by 2.2% and the median by 4.9% — but they cost 2.4 times the
time, which over the whole set is days rather than hours.

So the harder search is spent where it pays: on the tail, selected by the error
the first pass actually recorded. Roughly three hours for the worst 5%, against
thirty for the whole set.

**It cannot make anything worse.** A recipe is replaced only when the new fit
scores lower, and the search itself takes the best of its attempts. Adding
starting points can only find a deeper valley or the same one.

**Why a separate command and not a flag on the fitting pass.** That pass consults
the manifest and nothing else, so an edit it has already fitted is invisible to
it — which is exactly the property that makes it resumable. This one starts from
the opposite end: it reads what is stored, picks the worst, and updates in place.
"""

import os

for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

from photoassistant import fitting  # noqa: E402
from photoassistant.storage import (  # noqa: E402
    DatabaseConfig,
    Manifest,
    connect,
    step_refit,
)

from pipeline.environment import load  # noqa: E402
from pipeline.fit_all import DEFAULT_WORKERS, fit_one, read_jsonl, staging_dir  # noqa: E402

REPORT = Path(__file__).parent / "refit_report.json"

# Six offsets instead of two, spread across the range rather than clustered near
# zero: a local minimum is escaped by starting in another basin, not by starting
# further along the same slope.
WIDE_STARTS = (0.05, -0.05, 0.3, -0.3, 0.6, -0.6)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fraction",
        type=float,
        default=0.05,
        help="share of the worst-fitted edits to search again (default 0.05)",
    )
    parser.add_argument(
        "--above",
        type=float,
        default=0.0,
        help="instead of a share, take every edit whose error exceeds this dE",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--stride", type=int, default=6)
    parser.add_argument("--diff-step", type=float, default=3e-3)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually run. Without it, this reports what it would do and stops.",
    )
    return parser.parse_args()


def select(connection, arguments: argparse.Namespace) -> list[dict]:
    """The edits to search again, worst first, minus those already searched again."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.source_reference, e.expert, e.fit_error, e.id
              FROM examples e
              JOIN photos p ON p.id = e.photo_id
             WHERE NOT e.excluded_from_fitting
             ORDER BY e.fit_error DESC
            """
        )
        rows = [
            {"reference": reference, "expert": expert, "fit_error": error, "id": str(identifier)}
            for reference, expert, error, identifier in cursor.fetchall()
        ]

    if arguments.above > 0:
        chosen = [row for row in rows if row["fit_error"] > arguments.above]
    else:
        chosen = rows[: max(1, int(len(rows) * arguments.fraction))]

    tracker = Manifest(connection)
    experts = {row["expert"] for row in chosen}
    done = {expert: tracker.done_references(step_refit(expert)) for expert in experts}
    return [row for row in chosen if row["reference"] not in done[row["expert"]]]


def improve(connection, row: dict, result: dict) -> bool:
    """Replace the recipe only if the new one is closer. Returns whether it was.

    The comparison is against the value stored on the row rather than the one
    read at selection time, so two passes racing or a restart mid-run cannot undo
    an improvement that has already landed.
    """
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE examples
               SET edit = %s, fit_error = %s
             WHERE id = %s AND fit_error > %s
            """,
            (json.dumps(result["edit"]), result["mean_delta_e"], row["id"],
             result["mean_delta_e"]),
        )
        replaced = cursor.rowcount > 0

        cursor.execute(
            """
            INSERT INTO ingest_status (photo_reference, step, status, error, updated_at)
            VALUES (%s, %s, 'Done', NULL, now())
            ON CONFLICT (photo_reference, step) DO UPDATE
                SET status = 'Done', error = NULL, updated_at = now()
            """,
            (row["reference"], step_refit(row["expert"])),
        )
    return replaced


def main() -> None:
    arguments = parse_arguments()
    load()

    # Applies to the workers this process spawns, since they inherit the module.
    fitting.STARTS = WIDE_STARTS

    analytic = {}
    for edit in read_jsonl(staging_dir() / "edits.jsonl"):
        analytic[f"{edit['reference']}:{edit['expert']}"] = edit.get("analytic")

    database = DatabaseConfig.from_environment()
    with connect(database) as reader:
        chosen = select(reader, arguments)

    if not chosen:
        print("nothing left to search again")
        return

    errors = [row["fit_error"] for row in chosen]
    print(f"selected {len(chosen)} edits")
    print(
        f"  error from {min(errors):.3f} to {max(errors):.3f}, "
        f"mean {sum(errors) / len(errors):.3f}"
    )
    print(f"  starts {len(WIDE_STARTS)} + analytic, stride {arguments.stride}")

    if not arguments.confirm:
        print("\ndry run. Re-run with --confirm.")
        return

    tasks = [
        {
            "reference": row["reference"],
            "expert": row["expert"],
            "before_key": f"fivek/{row['reference']}/pre512.png",
            "after_key": f"fivek/{row['reference']}/after512-{row['expert']}.png",
            "analytic": analytic.get(f"{row['reference']}:{row['expert']}"),
            "with_curve": True,
            "measure_curve_contribution": False,
            "stride": arguments.stride,
            "diff_step": arguments.diff_step,
            "extra_starts": True,
        }
        for row in chosen
    ]
    by_key = {f"{row['reference']}:{row['expert']}": row for row in chosen}

    print(f"\nworkers {arguments.workers}\n")
    began = time.perf_counter()
    replaced = 0
    unchanged = 0
    failures: list[dict] = []
    gains: list[float] = []

    with (
        connect(database, autocommit=False) as writer,
        ProcessPoolExecutor(max_workers=arguments.workers) as pool,
    ):
        futures = [pool.submit(fit_one, task) for task in tasks]
        for finished, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            key = f"{result['reference']}:{result['expert']}"

            if result["outcome"] != "done":
                failures.append(result)
                print(f"  FAILED {key}: {result['error']}")
            else:
                row = by_key[key]
                if improve(writer, row, result):
                    replaced += 1
                    gains.append(row["fit_error"] - result["mean_delta_e"])
                else:
                    unchanged += 1

            if finished % 25 == 0 or finished == len(futures):
                elapsed = time.perf_counter() - began
                left = (len(futures) - finished) * elapsed / finished
                mean_gain = sum(gains) / len(gains) if gains else 0.0
                print(
                    f"  {finished}/{len(futures)}  replaced {replaced}  "
                    f"mean gain {mean_gain:.3f} dE  left ~{left / 60:.0f} min"
                )

    elapsed = time.perf_counter() - began
    report = {
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "selected": len(chosen),
        "replaced": replaced,
        "unchanged": unchanged,
        "failed": len(failures),
        "hours": round(elapsed / 3600, 3),
        "mean_gain_where_replaced": round(sum(gains) / len(gains), 4) if gains else None,
        "total_gain": round(sum(gains), 3),
        "starts": len(WIDE_STARTS),
        "stride": arguments.stride,
        "diff_step": arguments.diff_step,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nreplaced {replaced} of {len(chosen)}, {unchanged} already best, "
          f"{len(failures)} failed, in {report['hours']} h")
    if gains:
        print(f"mean gain where replaced: {report['mean_gain_where_replaced']} dE")
    print(f"written: {REPORT}")


if __name__ == "__main__":
    main()
