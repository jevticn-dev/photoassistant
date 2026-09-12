"""Fit our eleven parameters to every expert edit (phase 2, tasks 5-7).

    uv run --project ml python -m pipeline.fit_all --sample 1000 --with-curve
    uv run --project ml python -m pipeline.fit_all

The heart of the phase. For each pair of images — Lightroom's neutral rendition
and one expert's result — it searches for the values of *our* parameters that,
run through *our* renderer, land closest to what the expert produced.

**The search is driven by the images, not by the catalogue.** The translated
settings are one starting point among three; delete them and this still works,
slightly worse. That distinction is ADR-2: reconstructing the result keeps the
expert's image as the measure throughout, while translating their parameters
would bake in an error nobody can bound.

**Parallel by process, not by thread.** One fit is a few seconds of pure NumPy,
and Python threads do not run arithmetic in parallel (notes stack/python §15).
The probe measured about 5 s per edit serially, which is 35 hours for 25.000;
eight processes bring that to a night's work rather than a week's.

**Results land in the database, not in a file.** The row in ``examples`` and the
manifest mark are written in **one transaction**, so a crash cannot leave a step
recorded as done with no recipe behind it — the case ``storage/database.py``
keeps ``autocommit=False`` for.
"""

import os

# Before NumPy is imported anywhere: each worker would otherwise start a BLAS
# thread pool sized to the whole machine, and eight processes times sixteen
# threads on eight cores is slower than doing it serially.
for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from photoassistant.fitting import fit  # noqa: E402
from photoassistant.schema import EditRecipe  # noqa: E402
from photoassistant.storage import (  # noqa: E402
    STEP_DERIVE_BEFORE,
    DatabaseConfig,
    Manifest,
    ObjectStorageConfig,
    ObjectStore,
    connect,
    step_derive_after,
    step_fit,
)
from PIL import Image  # noqa: E402

from pipeline.environment import REPOSITORY_ROOT, load  # noqa: E402
from pipeline.fivek.catalogue import EXPERTS  # noqa: E402

REPORT = Path(__file__).parent / "fit_report.json"

DEFAULT_WORKERS = max(1, (os.cpu_count() or 4) // 2)

# Six neutral offsets instead of the library's two, spread across the range
# rather than clustered near zero: a local minimum is escaped by starting in
# another basin, not by starting further along the same slope. Defined here and
# imported by refit_worst, so the two passes cannot drift apart.
WIDE_STARTS: tuple[float, ...] = (0.05, -0.05, 0.3, -0.3, 0.6, -0.6)

# Reused inside a worker process. Building an S3 client per edit would add a
# connection setup to every few seconds of arithmetic.
_STORE: dict[str, ObjectStore] = {}


def staging_dir() -> Path:
    return Path(os.environ.get("STAGING_DIR", REPOSITORY_ROOT / "pipeline/.work/staging"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"staging file missing: {path}. Run pipeline.parse_catalogue first.")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def store() -> ObjectStore:
    if "store" not in _STORE:
        _STORE["store"] = ObjectStore(ObjectStorageConfig.from_environment())
    return _STORE["store"]


def load_image(bucket: str, key: str) -> np.ndarray:
    """One stored derivative as sRGB floats in [0, 1], which is what the renderer takes."""
    data = store().get(bucket, key)
    pixels = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
    return pixels / np.float32(255.0)


def fit_one(task: dict) -> dict:
    """Fit one edit. Runs in a worker process; returns only what fits in a message."""
    began = time.perf_counter()
    try:
        bucket = store().derivatives
        before = load_image(bucket, task["before_key"])
        after = load_image(bucket, task["after_key"])

        if before.shape != after.shape:
            # Cropped edits are excluded by the parser, so a mismatch here is
            # something new. Reporting it beats silently resizing one to the
            # other, which would put a geometric error into a colour measurement.
            raise ValueError(f"shapes differ: before {before.shape}, after {after.shape}")

        extra = []
        if task.get("analytic"):
            extra.append(EditRecipe.model_validate(task["analytic"]))

        # More places to begin, spread across the range rather than clustered near
        # zero: a local minimum is escaped by starting in another basin, not by
        # starting further along the same slope.
        #
        # Carried in the task rather than set on the module. Workers are spawned
        # on Windows, so each one re-imports everything and starts from the
        # defaults — only what travels inside the task actually reaches them.
        result = fit(
            before,
            after,
            starts=task.get("starts"),
            extra_starts=extra,
            with_curve=task["with_curve"],
            stride=task["stride"],
            diff_step=task["diff_step"],
        )

        record = {
            "reference": task["reference"],
            "expert": task["expert"],
            "outcome": "done",
            "edit": result.recipe.model_dump(by_alias=True),
            "mean_delta_e": result.mean_delta_e,
            "median_delta_e": result.median_delta_e,
            "max_delta_e": result.max_delta_e,
            "at_bounds": result.at_bounds(),
            "converged": result.converged,
            "seconds": round(time.perf_counter() - began, 2),
        }

        if task["measure_curve_contribution"]:
            # What the sliders alone reach, so that "how much does the master
            # curve add" stays a measured number rather than plan §4.2's claim.
            sliders = fit(
                before,
                after,
                starts=task.get("starts"),
                extra_starts=extra,
                with_curve=False,
                stride=task["stride"],
                diff_step=task["diff_step"],
            )
            record["sliders_only_delta_e"] = sliders.mean_delta_e

        return record
    except Exception as error:  # noqa: BLE001 - one bad edit must not end the run
        return {
            "reference": task["reference"],
            "expert": task["expert"],
            "outcome": "failed",
            "error": f"{type(error).__name__}: {error}",
            "seconds": round(time.perf_counter() - began, 2),
        }


def ensure_photo_rows(connection, references: list[str], tags: dict[str, dict]) -> dict[str, str]:
    """Create the ``photos`` row for every photograph and return reference -> id.

    Done up front for all of them rather than on demand: it is one cheap pass, and
    it means the fitting loop never has to think about parents. The keys are
    deterministic from the reference, so they can be written before the fetcher
    has reached that photograph.
    """
    with connection.cursor() as cursor:
        for reference in references:
            cursor.execute(
                """
                INSERT INTO photos (id, source, pre512_key, proxy2048_key, source_reference,
                                    tags, created_at)
                VALUES (%s, 'Fivek', %s, %s, %s, %s, now())
                ON CONFLICT (source, source_reference) WHERE source_reference IS NOT NULL
                DO UPDATE SET tags = EXCLUDED.tags
                """,
                (
                    str(uuid.uuid4()),
                    f"fivek/{reference}/pre512.png",
                    f"fivek/{reference}/proxy2048.jpg",
                    reference,
                    json.dumps(tags.get(reference, {})),
                ),
            )
        cursor.execute(
            "SELECT source_reference, id FROM photos WHERE source = 'Fivek'"
        )
        return {reference: str(identifier) for reference, identifier in cursor.fetchall()}


def record_result(connection, photo_id: str, result: dict) -> None:
    """Write the example row and mark the step done, atomically.

    Not autocommit. The recipe is several seconds of work and the manifest mark
    claims it exists; if the two could be separated by a crash, a restart would
    skip an edit that has no row. Here either both land or neither does.
    """
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO examples (id, photo_id, edit, expert, fit_error, after_key,
                                  excluded_from_fitting, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, false, now())
            """,
            (
                str(uuid.uuid4()),
                photo_id,
                json.dumps(result["edit"]),
                result["expert"],
                result["mean_delta_e"],
                f"fivek/{result['reference']}/after512-{result['expert']}.png",
            ),
        )
        cursor.execute(
            """
            INSERT INTO ingest_status (photo_reference, step, status, error, updated_at)
            VALUES (%s, %s, 'Done', NULL, now())
            ON CONFLICT (photo_reference, step) DO UPDATE
                SET status = 'Done', error = NULL, updated_at = now()
            """,
            (result["reference"], step_fit(result["expert"])),
        )


def stratified(tasks: list[dict], size: int) -> list[dict]:
    """A sample balanced across experts and spread across the catalogue.

    Not the first N: names are grouped by photographer, so a prefix would measure
    a handful of cameras and scenes rather than the dataset.

    **And not a plain stride over the whole list either**, which is what this did
    at first. The list runs photograph by photograph with the five experts inside
    each, so it has a period of five — and a stride that shares a factor with that
    period revisits the same expert positions. Over 24.986 tasks it produced 269
    edits by expert C against 143 by expert E, nearly two to one.

    That matters because the experts are not equally easy to reconstruct: measured
    over this very sample, mean ΔE runs from 1.31 for B to 1.86 for C. An
    unbalanced sample therefore reports an average of whichever experts it
    happened to favour. The first run got away with it — the balanced mean was
    1.598 against 1.597 reported, because the over-represented easy and hard
    experts cancelled — but that was luck, not design.

    So the stride runs **within** each expert instead of across all of them.
    """
    if size <= 0 or size >= len(tasks):
        return tasks

    by_expert: dict[str, list[dict]] = {}
    for task in tasks:
        by_expert.setdefault(task["expert"], []).append(task)

    experts = sorted(by_expert)
    share, remainder = divmod(size, len(experts))

    sample: list[dict] = []
    for position, expert in enumerate(experts):
        group = by_expert[expert]
        # The remainder is spread over the first few groups rather than dropped,
        # so the sample is the size that was asked for. Without it, asking for
        # fewer edits than there are experts returns nothing at all.
        wanted = share + (1 if position < remainder else 0)
        take = min(wanted, len(group))
        if take == 0:
            continue
        step = len(group) / take
        sample.extend(group[int(index * step)] for index in range(take))

    return sample


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experts", default="".join(EXPERTS))
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="fit a stratified sample of this many edits; 0 fits everything available",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--diff-step",
        type=float,
        default=3e-3,
        help=(
            "how far a parameter is nudged to estimate the Jacobian. Measured over "
            "the 50 hardest fits: 3e-3 lands better than 1e-2 on 41 of 50 and worse "
            "on 4; 3e-2 is worse on 45 of 50. The single largest effect found in "
            "phase 2, and it was a value nobody had revisited since the probe."
        ),
    )
    parser.add_argument(
        "--extra-starts",
        action="store_true",
        help=(
            "search from six neutral offsets instead of two. Cannot make a fit "
            "worse — the best attempt wins — and improves the hardest 50 by 2.2%% "
            "in the mean, for 2.4 times the time."
        ),
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=4,
        help=(
            "fit on every Nth pixel. Measured on 4 edits with the machine busy: "
            "stride 4 costs 18.7 s/edit for mean dE 1.304, stride 8 costs 4.9 s for "
            "1.360. Almost four times faster for 0.056 dE, which is a twentieth of "
            "the threshold where a difference becomes visible at all."
        ),
    )
    parser.add_argument(
        "--no-curve",
        action="store_true",
        help="fit the ten sliders only, leaving the master curve neutral",
    )
    parser.add_argument(
        "--measure-curve-contribution",
        action="store_true",
        help="also fit without the curve, to report what it adds. Doubles the time.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_tasks(arguments: argparse.Namespace) -> tuple[list[dict], dict[str, int]]:
    """Every edit that can be fitted right now, with the reasons the rest cannot."""
    edits = read_jsonl(staging_dir() / "edits.jsonl")
    experts = tuple(character for character in arguments.experts if character in EXPERTS)

    database = DatabaseConfig.from_environment()
    with connect(database) as connection:
        tracker = Manifest(connection)
        have_before = tracker.done_references(STEP_DERIVE_BEFORE)
        have_after = {expert: tracker.done_references(step_derive_after(expert))
                      for expert in experts}
        already_fitted = {expert: tracker.done_references(step_fit(expert))
                          for expert in experts}

    skipped: dict[str, int] = {}
    tasks: list[dict] = []
    for edit in edits:
        expert = edit["expert"]
        reference = edit["reference"]
        if expert not in experts:
            continue
        if edit["excluded_reason"]:
            skipped[f"excluded:{edit['excluded_reason']}"] = (
                skipped.get(f"excluded:{edit['excluded_reason']}", 0) + 1
            )
            continue
        if reference in already_fitted[expert]:
            skipped["already fitted"] = skipped.get("already fitted", 0) + 1
            continue
        if reference not in have_before or reference not in have_after[expert]:
            skipped["not downloaded yet"] = skipped.get("not downloaded yet", 0) + 1
            continue

        tasks.append(
            {
                "reference": reference,
                "expert": expert,
                "before_key": f"fivek/{reference}/pre512.png",
                "after_key": f"fivek/{reference}/after512-{expert}.png",
                "analytic": edit.get("analytic"),
                "with_curve": not arguments.no_curve,
                "measure_curve_contribution": arguments.measure_curve_contribution,
                "stride": arguments.stride,
                "diff_step": arguments.diff_step,
                "starts": WIDE_STARTS if arguments.extra_starts else None,
            }
        )
    return tasks, skipped


def main() -> None:
    arguments = parse_arguments()
    load()

    tasks, skipped = build_tasks(arguments)
    print(f"fittable now {len(tasks)}   skipped {skipped}")

    if arguments.sample:
        tasks = stratified(tasks, arguments.sample)
        print(f"stratified sample: {len(tasks)}")

    if arguments.dry_run or not tasks:
        print("dry run: stopping here" if tasks else "nothing to fit")
        return

    photos = read_jsonl(staging_dir() / "photos.jsonl")
    tags = {row["reference"]: row.get("tags", {}) for row in photos}

    database = DatabaseConfig.from_environment()
    with connect(database) as setup:
        identifiers = ensure_photo_rows(setup, sorted(tags), tags)
    print(f"photos rows ready: {len(identifiers)}")
    print(f"workers {arguments.workers}   curve {'off' if arguments.no_curve else 'on'}\n")

    results: list[dict] = []
    began = time.perf_counter()

    # A transactional connection, because each result is written together with
    # its manifest mark.
    with (
        connect(database, autocommit=False) as writer,
        ProcessPoolExecutor(max_workers=arguments.workers) as pool,
    ):
        futures = [pool.submit(fit_one, task) for task in tasks]
        for finished, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)

            if result["outcome"] == "done":
                record_result(writer, identifiers[result["reference"]], result)
            else:
                print(f"  FAILED {result['reference']} {result['expert']}: {result['error']}")

            if finished % 25 == 0 or finished == len(futures):
                _progress(finished, len(futures), results, began)

    write_report(results, time.perf_counter() - began, arguments)


def _progress(finished: int, total: int, results: list[dict], began: float) -> None:
    elapsed = time.perf_counter() - began
    errors = sorted(r["mean_delta_e"] for r in results if r["outcome"] == "done")
    median = errors[len(errors) // 2] if errors else float("nan")
    remaining = (total - finished) * elapsed / finished if finished else 0.0
    print(
        f"  {finished}/{total}  median dE {median:.2f}  "
        f"{elapsed / finished:.1f} s/edit  left ~{remaining / 60:.0f} min"
    )


def write_report(results: list[dict], elapsed: float, arguments: argparse.Namespace) -> None:
    done = [r for r in results if r["outcome"] == "done"]
    failed = [r for r in results if r["outcome"] == "failed"]
    errors = sorted(r["mean_delta_e"] for r in done)

    def percentile(fraction: float) -> float | None:
        if not errors:
            return None
        return round(errors[min(len(errors) - 1, int(len(errors) * fraction))], 3)

    at_bounds: dict[str, int] = {}
    for result in done:
        for name in result["at_bounds"]:
            at_bounds[name] = at_bounds.get(name, 0) + 1

    report: dict[str, object] = {
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fitted": len(done),
        "failed": len(failed),
        "hours": round(elapsed / 3600, 3),
        "wall_seconds_per_edit": round(elapsed / len(results), 2) if results else None,
        # Per edit inside a worker, which is what a projection needs: the wall
        # figure above depends on how many workers ran and what else the machine
        # was doing.
        "cpu_seconds_per_edit": (
            round(sum(r["seconds"] for r in results) / len(results), 2) if results else None
        ),
        "stride": arguments.stride,
        "diff_step": arguments.diff_step,
        "extra_starts": arguments.extra_starts,
        "workers": arguments.workers,
        "delta_e": {
            "mean": round(sum(errors) / len(errors), 3) if errors else None,
            "median": percentile(0.5),
            "p90": percentile(0.9),
            "p99": percentile(0.99),
            "max": round(errors[-1], 3) if errors else None,
        },
        # A parameter pinned at its limit usually means the scale is too weak to
        # express what the expert did, not that the edit was extreme. This is the
        # number ADR-19 was made of, and the one the calibration pass watches.
        "at_bounds": dict(sorted(at_bounds.items(), key=lambda item: -item[1])),
        "not_converged": sum(1 for r in done if not r["converged"]),
        "failures": [{"reference": r["reference"], "expert": r["expert"], "error": r["error"]}
                     for r in failed][:50],
    }

    contributions = [
        r["sliders_only_delta_e"] - r["mean_delta_e"]
        for r in done
        if "sliders_only_delta_e" in r
    ]
    if contributions:
        shares = sorted(
            (r["sliders_only_delta_e"] - r["mean_delta_e"]) / r["sliders_only_delta_e"]
            for r in done
            if r.get("sliders_only_delta_e")
        )
        report["curve_contribution"] = {
            "mean_share": round(sum(shares) / len(shares), 3),
            "median_share": round(shares[len(shares) // 2], 3),
        }

    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nfitted {len(done)}  failed {len(failed)}  in {report['hours']} h")
    print(f"dE  mean {report['delta_e']['mean']}  median {report['delta_e']['median']}  "
          f"p90 {report['delta_e']['p90']}  max {report['delta_e']['max']}")
    print(f"at bounds: {report['at_bounds']}")
    print(f"written: {REPORT}")


if __name__ == "__main__":
    main()
