"""How far apart five experts are on the same photograph (phase 3, task 8).

    uv run --project ml python -m pipeline.measure_expert_agreement

Every threshold in the exam is read out of this number rather than chosen. Asking
"are three suggestions different enough" needs a scale, and the scale already
exists in the data: five people edited each photograph and disagreed, and how much
they disagreed is measurable (§B39).

**Two scales, not one, because they answer different questions.**

``human``
    pairwise ΔE between the five expert renditions themselves. What people
    actually did — the target our suggestions are compared against.

``reachable``
    pairwise ΔE between **our fitted recipes** of those same five edits, rendered
    on the neutral image. The most variety edit schema v1 can express at all.

The gap between them is the price of the schema's expressiveness, in the same unit
as everything else. A suggestion set cannot be more varied than ``reachable``, so
reporting only ``human`` would hold the system to a bar it cannot reach by
construction.

``fingerprint`` is the same disagreement measured in fingerprint space, and exists
so the two diversity figures can be compared at all (§B72).

**Run once, then left alone.** The artefact it writes is read by every later run;
a threshold moved after seeing results is not a threshold.
"""

import os

# Before NumPy: eight workers each starting a BLAS pool sized to the whole machine
# is slower than doing this serially (§B27).
for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from photoassistant.recommender import EvaluationSplit  # noqa: E402
from photoassistant.recommender.metrics import (  # noqa: E402
    mean_pairwise_delta_e,
    mean_pairwise_distance,
    median_pairwise_delta_e,
)
from photoassistant.recommender.stores import parse_vector  # noqa: E402
from photoassistant.renderer import render, srgb_to_lab  # noqa: E402
from photoassistant.schema import EditRecipe  # noqa: E402
from photoassistant.storage import DatabaseConfig, connection  # noqa: E402

from pipeline import derivative_cache  # noqa: E402
from pipeline.environment import REPOSITORY_ROOT, load  # noqa: E402
from pipeline.make_split import SPLIT_PATH  # noqa: E402

REPORT = Path(
    os.environ.get("AGREEMENT_REPORT")
    or REPOSITORY_ROOT / "pipeline/reports/expert_agreement.json"
)

# How many build-set photographs the control pass measures. Not a second
# experiment: it exists only to show that the 500 held out are not unusual.
#
# Matched to the held-out set on purpose. A first run used a hundred and the two
# medians came out 0,74 apart, which is about two standard errors of a median at
# that sample size — indistinguishable from "the split is skewed" and from "the
# control was small". Five minutes of measurement settles which, and a comparison
# whose two sides have different precision is not a comparison.
CONTROL_SAMPLE = 500
CONTROL_SEED = 20260913

PHOTOGRAPH_SQL = """
SELECT p.source_reference, p.pre512_key, e.expert, e.edit,
       e.after_key, e.style_fingerprint::text
  FROM photos p
  JOIN examples e ON e.photo_id = p.id
 WHERE p.source_reference = ANY(%(references)s)
   AND NOT e.excluded_from_fitting
   AND e.style_fingerprint IS NOT NULL
   AND e.after_key IS NOT NULL
 ORDER BY p.source_reference, e.expert
"""


def read_photographs(handle, references: list[str]) -> dict[str, dict]:
    """Everything one photograph needs, grouped by reference."""
    with handle.cursor() as cursor:
        cursor.execute(PHOTOGRAPH_SQL, {"references": references})
        rows = cursor.fetchall()

    grouped: dict[str, dict] = {}
    for reference, pre512_key, expert, edit, after_key, fingerprint in rows:
        entry = grouped.setdefault(reference, {"pre512_key": pre512_key, "experts": []})
        entry["experts"].append(
            {
                "expert": expert,
                "edit": edit,
                "after_key": after_key,
                "fingerprint": fingerprint,
            }
        )
    return grouped


def measure_one(task: dict) -> dict:
    """The three scales for one photograph. Runs in a worker process."""
    reference = task["reference"]
    try:
        expert_labs = [
            srgb_to_lab(derivative_cache.image(entry["after_key"])) for entry in task["experts"]
        ]

        neutral = derivative_cache.image(task["pre512_key"])
        reachable_labs = [
            srgb_to_lab(render(neutral, EditRecipe.model_validate(entry["edit"])))
            for entry in task["experts"]
        ]

        fingerprints = [parse_vector(entry["fingerprint"]) for entry in task["experts"]]

        return {
            "reference": reference,
            "outcome": "done",
            "experts": len(expert_labs),
            "human_mean": mean_pairwise_delta_e(expert_labs),
            "human_median": median_pairwise_delta_e(expert_labs),
            "reachable_mean": mean_pairwise_delta_e(reachable_labs),
            "reachable_median": median_pairwise_delta_e(reachable_labs),
            "fingerprint_mean": mean_pairwise_distance(fingerprints),
        }
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return {
            "reference": reference,
            "outcome": "failed",
            "error": f"{type(error).__name__}: {error}",
        }


def distribution(values: list[float]) -> dict[str, float]:
    array = np.array([value for value in values if value is not None], dtype=np.float64)
    if not len(array):
        return {}
    return {
        "count": int(len(array)),
        "min": float(array.min()),
        "p10": float(np.percentile(array, 10)),
        "median": float(np.median(array)),
        "mean": float(array.mean()),
        "p90": float(np.percentile(array, 90)),
        "max": float(array.max()),
    }


def run(tasks: list[dict], workers: int, label: str) -> tuple[list[dict], list[dict]]:
    print(f"{label}: {len(tasks)} photographs on {workers} workers")
    began = time.perf_counter()
    done: list[dict] = []
    failures: list[dict] = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(measure_one, task) for task in tasks]
        for finished, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            (done if result["outcome"] == "done" else failures).append(result)
            if finished % 50 == 0 or finished == len(tasks):
                elapsed = time.perf_counter() - began
                rate = finished / elapsed
                print(
                    f"  {finished}/{len(tasks)}  {elapsed / 60:.1f} min elapsed, "
                    f"{(len(tasks) - finished) / rate / 60:.1f} min left"
                )

    return done, failures


def summarise(results: list[dict]) -> dict:
    return {
        "human_mean": distribution([r["human_mean"] for r in results]),
        "human_median": distribution([r["human_median"] for r in results]),
        "reachable_mean": distribution([r["reachable_mean"] for r in results]),
        "reachable_median": distribution([r["reachable_median"] for r in results]),
        "fingerprint_mean": distribution([r["fingerprint_mean"] for r in results]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure how far apart the five experts are.")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument(
        "--control-sample",
        type=int,
        default=CONTROL_SAMPLE,
        help="how many build-set photographs the control pass measures",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="measure only the first N photographs (a smoke run)",
    )
    parser.add_argument(
        "--no-control",
        action="store_true",
        help="skip the build-set control pass",
    )
    arguments = parser.parse_args()

    load()
    split = EvaluationSplit.load(SPLIT_PATH)

    with connection(DatabaseConfig.from_environment()) as handle:
        held_out = read_photographs(handle, list(split.held_out))

        control_references: list[str] = []
        if not arguments.no_control:
            with handle.cursor() as cursor:
                cursor.execute(
                    "SELECT source_reference FROM photos WHERE source = 'Fivek' "
                    "ORDER BY source_reference"
                )
                every = [reference for (reference,) in cursor.fetchall()]
            build = [reference for reference in every if not split.is_held_out(reference)]
            generator = np.random.default_rng(CONTROL_SEED)
            sample = min(arguments.control_sample, len(build))
            control_references = sorted(
                str(reference)
                for reference in generator.choice(build, size=sample, replace=False)
            )
            control = read_photographs(handle, control_references)

    def tasks_for(grouped: dict[str, dict]) -> list[dict]:
        prepared = [
            {"reference": reference, **entry}
            for reference, entry in sorted(grouped.items())
            if entry["pre512_key"] and len(entry["experts"]) >= 2
        ]
        return prepared[: arguments.limit] if arguments.limit else prepared

    held_out_results, failures = run(tasks_for(held_out), arguments.workers, "held out")
    control_results: list[dict] = []
    if control_references:
        control_results, control_failures = run(
            tasks_for(control), arguments.workers, "control (build set)"
        )
        failures.extend(control_failures)

    report = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "split_seed": split.seed,
        "held_out": {
            "photographs": len(held_out_results),
            **summarise(held_out_results),
        },
        "control": {
            "photographs": len(control_results),
            **summarise(control_results),
        },
        "per_photograph": {
            result["reference"]: {
                key: result[key]
                for key in (
                    "experts",
                    "human_mean",
                    "human_median",
                    "reachable_mean",
                    "reachable_median",
                    "fingerprint_mean",
                )
            }
            for result in sorted(held_out_results, key=lambda r: r["reference"])
        },
        "failures": failures,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print()
    for name, section in (("held out", report["held_out"]), ("control", report["control"])):
        if not section["photographs"]:
            continue
        human = section["human_median"]
        reachable = section["reachable_median"]
        print(
            f"{name:<10} photographs {section['photographs']:>4}   "
            f"human median {human['median']:.3f} "
            f"(p10 {human['p10']:.3f}, p90 {human['p90']:.3f})   "
            f"reachable median {reachable['median']:.3f}"
        )
    print(f"\nwritten to {REPORT}")

    if failures:
        print(f"\nFAILED on {len(failures)} photographs:", file=sys.stderr)
        for failure in failures[:10]:
            print(f"  {failure['reference']}: {failure['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
