"""What the approximate index costs in accuracy, and buys in time (phase 3, task 13).

    uv run --project ml python -m pipeline.measure_index

Phase 2 proved the HNSW index is **used**. This asks the two questions that proof
left open: how much of the exact answer it returns, and whether the difference ever
reaches the user.

**Three query shapes, because the system really has three.**

``approximate``
    no filter, index used. What a request from a user runs.

``exact``
    no filter, ``enable_indexscan = off``. The ground truth the first is compared
    against.

``filtered``
    the exclusion set applied, which Postgres answers by scanning exactly anyway
    (§B54). What every number in this phase was measured on.

**The first run of this found a defect in the production path**, which is what it
was for: at pgvector's default ``hnsw.ef_search`` of 40 the index cannot return
more than 40 rows, so a query asking for the planned 50 neighbours came back with
40 — silently, with recall exactly 0,80 on every single query. The evaluation never
saw it because its filtered queries scan exactly. The store now widens the walk to
twice ``k`` before searching.

The third is the reason this matters: the evaluation ran on a **more accurate**
path than production, so the numbers here say by how much — and whether the answer
changes at all, which is the only part a user could notice.

**Recall is not the interesting number; the three suggestions are.** An index can
miss a neighbour that would never have been chosen, and that costs nothing. Both
are reported, and they do not have to agree.
"""

import argparse
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from photoassistant.recommender import EvaluationSplit, PostgresVectorStore, TopCandidates
from photoassistant.recommender.stores import parse_vector
from photoassistant.storage import DatabaseConfig, connect

from pipeline.environment import REPOSITORY_ROOT, load
from pipeline.make_split import SPLIT_PATH

REPORT = Path(
    os.environ.get("INDEX_REPORT") or REPOSITORY_ROOT / "pipeline/reports/index.json"
)

NEIGHBOURS = 50
SUGGESTIONS = 3


def query_vectors(connection, split: EvaluationSplit) -> list[tuple[str, np.ndarray]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_reference, clip_embedding::text
              FROM photos
             WHERE source_reference = ANY(%s) AND clip_embedding IS NOT NULL
             ORDER BY source_reference
            """,
            (list(split.held_out),),
        )
        return [(reference, parse_vector(literal)) for reference, literal in cursor.fetchall()]


def timed(store, vector, exclude):
    began = time.perf_counter()
    result = store.neighbours(vector, count=NEIGHBOURS, exclude=exclude)
    return result, time.perf_counter() - began


def suggestions_from(store, found, reference: str) -> tuple[str, ...]:
    """The three the shipped strategy would choose from this neighbour list.

    The query photograph is dropped here rather than in SQL: filtering in the query
    would change the plan and turn the approximate path into an exact one, which is
    the very thing being compared.
    """
    pool = [
        candidate
        for candidate in store.candidates(found)
        if candidate.photo_reference != reference
    ]
    chosen = TopCandidates(one_per_photograph=True, prefer_best_fit=True).select(
        pool, SUGGESTIONS
    )
    return tuple(entry.example_id for entry in chosen)


def summarise(values: list[float]) -> dict[str, float]:
    array = np.array(values, dtype=np.float64)
    return {
        "median_ms": float(np.median(array) * 1000),
        "mean_ms": float(array.mean() * 1000),
        "p95_ms": float(np.percentile(array, 95) * 1000),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the index against exact search.")
    parser.add_argument("--limit", type=int, help="only the first N queries")
    arguments = parser.parse_args()

    load()
    configuration = DatabaseConfig.from_environment()
    split = EvaluationSplit.load(SPLIT_PATH)

    with connect(configuration) as indexed, connect(configuration) as scanned:
        # One connection keeps the index, the other is told not to use it. Session
        # level rather than per statement, so no query can accidentally run on the
        # wrong side of the comparison.
        with scanned.cursor() as cursor:
            cursor.execute("SET enable_indexscan = off")
            cursor.execute("SET enable_bitmapscan = off")

        queries = query_vectors(indexed, split)
        if arguments.limit:
            queries = queries[: arguments.limit]

        approximate = PostgresVectorStore(indexed)
        exact = PostgresVectorStore(scanned)
        hidden = split.held_out_set

        # Warm-up before any timing. The first queries pay for plan caching and
        # pages coming off disk; without this the control at the end looks 56%
        # faster than the start and the comparison between shapes is unusable
        # (§B22).
        for _, vector in queries[: min(30, len(queries))]:
            timed(approximate, vector, frozenset())
            timed(exact, vector, frozenset())

        recalls: list[float] = []
        changed = 0
        answered = 0
        times = {"approximate": [], "exact": [], "filtered": [], "control": []}

        for index, (reference, vector) in enumerate(queries, start=1):
            found_a, seconds_a = timed(approximate, vector, frozenset())
            found_e, seconds_e = timed(exact, vector, frozenset())
            _, seconds_f = timed(approximate, vector, hidden)

            times["approximate"].append(seconds_a)
            times["exact"].append(seconds_e)
            times["filtered"].append(seconds_f)

            names_a = {entry.reference for entry in found_a}
            names_e = {entry.reference for entry in found_e}
            recalls.append(len(names_a & names_e) / max(len(names_e), 1))

            if names_a != names_e:
                answered += 1
                if suggestions_from(approximate, found_a, reference) != suggestions_from(
                    exact, found_e, reference
                ):
                    changed += 1

            if index % 100 == 0:
                print(f"  {index}/{len(queries)}")

        # The control from §B22: repeat the first measurement at the end. If the
        # machine drifted during the run, the comparison between shapes is not
        # usable, and this is the only way to know.
        for _, vector in queries[: min(50, len(queries))]:
            _, seconds = timed(approximate, vector, frozenset())
            times["control"].append(seconds)

    first = statistics.median(times["approximate"][: len(times["control"])])
    control = statistics.median(times["control"])
    drift = abs(control - first) / first * 100 if first else 0.0

    report = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "queries": len(queries),
        "neighbours": NEIGHBOURS,
        "recall": {
            "mean": float(np.mean(recalls)),
            "median": float(np.median(recalls)),
            "minimum": float(np.min(recalls)),
            "perfect_share": float(np.mean([value == 1.0 for value in recalls])),
        },
        "neighbour_lists_differing": answered,
        "suggestions_differing": changed,
        "latency": {shape: summarise(values) for shape, values in times.items()},
        "control_drift_percent": drift,
    }

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nqueries {report['queries']}, k = {NEIGHBOURS}")
    print(
        f"recall  mean {report['recall']['mean']:.4f}   "
        f"perfect on {report['recall']['perfect_share'] * 100:.1f}% of queries   "
        f"worst {report['recall']['minimum']:.2f}"
    )
    print(
        f"answers differing: neighbour lists {answered}/{len(queries)}, "
        f"suggestions {changed}/{len(queries)}"
    )
    for shape, values in report["latency"].items():
        print(
            f"{shape:<12} median {values['median_ms']:6.2f} ms   p95 {values['p95_ms']:6.2f} ms"
        )
    print(f"control drift {drift:.1f}%  (§B22: above a few per cent the comparison is unusable)")
    print(f"\nwritten to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
