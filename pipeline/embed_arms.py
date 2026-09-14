"""Fingerprints for the arms that need a model (phase 3, task 11).

    uv run --project ml --extra embeddings python -m pipeline.embed_arms --measure 64
    uv run --project ml --extra embeddings python -m pipeline.embed_arms --arm after
    uv run --project ml --extra embeddings python -m pipeline.embed_arms --arm difference

Two compositions, both an encoder over an image:

``after``
    the edited result. The arm the mentor's review predicted would mostly describe
    the **scene** rather than the edit — kept as the baseline the others must beat,
    because without it nobody knows whether the rest bring anything (§B39).

``difference``
    ``(after − before) / 2 + 0,5``. Colour statistics are global averages and
    cannot say "the sky darkened while the face brightened"; a difference image
    keeps *where* (§B62). The rescaling makes it a valid grey-centred image, and it
    is still not a photograph — if this arm fails, the failure does not separate
    "the idea is wrong" from "the encoder could not read this input" (§B58).

**Written to files, never to the database.** 384 numbers do not fit a
``vector(30)`` column, and the column changes only if an arm wins — together with
its scaling constants, never one without the other (decision D).

**The throughput is measured before any full pass**, as decision E requires. It
already changed a default: DINOv2 at its native 518px runs at 4,3 img/s against
28,9 at 224px, which is 97 minutes a pass against 14.
"""

import os

for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from photoassistant.storage import DatabaseConfig, connect  # noqa: E402

from pipeline import derivative_cache  # noqa: E402
from pipeline.environment import REPOSITORY_ROOT, load  # noqa: E402

VECTORS = Path(
    os.environ.get("ARM_VECTORS") or REPOSITORY_ROOT / "pipeline/.work/fingerprints"
)
REPORT = Path(
    os.environ.get("ARMS_REPORT") or REPOSITORY_ROOT / "pipeline/reports/embed_arms.json"
)

# Images per forward pass. Larger batches amortise the per-call overhead; beyond
# this the gain is noise and the memory is not.
BATCH = 32

EXAMPLES_SQL = """
SELECT e.id, p.pre512_key, e.after_key
  FROM examples e
  JOIN photos p ON p.id = e.photo_id
 WHERE NOT e.excluded_from_fitting
   AND e.after_key IS NOT NULL
   AND p.pre512_key IS NOT NULL
 ORDER BY e.id
"""


def encoder(name: str):
    """Build one of the two encoders. Imported here, never at module scope."""
    if name == "dinov2":
        from photoassistant.embeddings.dinov2 import Dinov2Config, Dinov2Encoder

        return Dinov2Encoder(Dinov2Config.from_environment())
    if name == "clip":
        from photoassistant.embeddings.clip import ClipEncoder

        return ClipEncoder()
    raise SystemExit(f"unknown encoder {name!r}; expected 'dinov2' or 'clip'")


def image_for(arm: str, row: dict) -> np.ndarray:
    """The one image this arm encodes, built from what is in storage."""
    after = derivative_cache.image(row["after_key"])
    if arm == "after":
        return after

    before = derivative_cache.image(row["pre512_key"])
    # Grey means "nothing changed": the difference is centred on 0,5 rather than on
    # zero, so the result is a valid image in [0, 1] instead of half-negative
    # numbers the encoder's preprocessing would clip away (§B58).
    return np.clip((after - before) / 2.0 + 0.5, 0.0, 1.0)


def probe_examples(connection, queries: int, neighbours: int) -> set[str]:
    """Example ids that can appear in the pools of the first ``queries`` questions.

    A probe cannot encode "a sample of the edits": the fingerprint is used to choose
    **within a pool**, and a candidate without a vector in this arm would have to be
    dropped or given zeros, either of which decides the comparison by itself.

    So the experiment shrinks instead of the data. Fewer questions and a smaller
    ``k`` make the union of pools small enough to encode at a resolution that costs
    seven times more — and the comparison stays honest, because both sides run over
    exactly these questions with exactly this ``k``.
    """
    from photoassistant.recommender import EvaluationSplit, PostgresVectorStore
    from photoassistant.recommender.stores import parse_vector

    from pipeline.make_split import SPLIT_PATH

    split = EvaluationSplit.load(SPLIT_PATH)
    store = PostgresVectorStore(connection)

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
        asked = cursor.fetchall()[:queries]

    references: set[str] = set()
    for _, literal in asked:
        found = store.neighbours(
            parse_vector(literal), count=neighbours, exclude=split.held_out_set
        )
        references.update(entry.reference for entry in found)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.id
              FROM examples e
              JOIN photos p ON p.id = e.photo_id
             WHERE p.source_reference = ANY(%s) AND NOT e.excluded_from_fitting
            """,
            (sorted(references),),
        )
        identifiers = {str(identifier) for (identifier,) in cursor.fetchall()}

    print(f"probe: {len(asked)} questions x k={neighbours} -> "
          f"{len(references)} photographs, {len(identifiers)} examples")
    return identifiers


def rows(connection, limit: int | None) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(EXAMPLES_SQL)
        found = [
            {"id": str(identifier), "pre512_key": pre512, "after_key": after}
            for identifier, pre512, after in cursor.fetchall()
        ]
    return found[:limit] if limit else found


def run_measure(arm: str, model, tasks: list[dict], count: int) -> dict:
    """Throughput on a small pile, and the projection it licenses (§B48)."""
    sample = tasks[:count]
    images = [image_for(arm, row) for row in sample]

    model.encode(images[:4])  # warm-up: the first call builds lazily
    began = time.perf_counter()
    vectors = model.encode(images[: min(count, len(images))])
    elapsed = time.perf_counter() - began

    rate = len(vectors) / elapsed
    return {
        "arm": arm,
        "encoder": model.describe(),
        "images": len(vectors),
        "images_per_second": round(rate, 2),
        "projected_minutes_for_all": round(len(tasks) / rate / 60, 1),
        "note": "encoder only; loading images from the cache is extra",
    }


def run_arm(arm: str, name: str, model, tasks: list[dict]) -> dict:
    """Encode every example and write one ``.npz`` for this composition."""
    identifiers: list[str] = []
    vectors: list[np.ndarray] = []
    began = time.perf_counter()

    for start in range(0, len(tasks), BATCH):
        chunk = tasks[start : start + BATCH]
        images = [image_for(arm, row) for row in chunk]
        vectors.append(model.encode(images))
        identifiers.extend(row["id"] for row in chunk)

        finished = len(identifiers)
        if finished % (BATCH * 20) == 0 or finished == len(tasks):
            elapsed = time.perf_counter() - began
            rate = finished / elapsed
            print(
                f"  {finished}/{len(tasks)}  {elapsed / 60:.1f} min elapsed, "
                f"{(len(tasks) - finished) / rate / 60:.1f} min left",
                flush=True,
            )

    stack = np.vstack(vectors)
    VECTORS.mkdir(parents=True, exist_ok=True)
    path = VECTORS / f"{name}.npz"
    np.savez_compressed(path, identifiers=np.array(identifiers), vectors=stack.astype(np.float32))

    return {
        "arm": arm,
        "name": name,
        "encoder": model.describe(),
        "examples": len(identifiers),
        "dimension": int(stack.shape[1]),
        "minutes": round((time.perf_counter() - began) / 60, 1),
        "path": str(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute fingerprints for the model arms.")
    parser.add_argument("--arm", choices=("after", "difference"), help="which composition")
    parser.add_argument("--encoder", default="dinov2", choices=("dinov2", "clip"))
    parser.add_argument("--measure", type=int, metavar="N", help="measure throughput on N images")
    parser.add_argument("--limit", type=int, help="only the first N examples (a smoke run)")
    parser.add_argument("--name", help="output file name (default: <arm>-<encoder>)")
    parser.add_argument(
        "--pool-probe",
        metavar="QUERIES:K",
        help="encode only what can appear in the pools of a smaller experiment",
    )
    arguments = parser.parse_args()

    if not arguments.arm and not arguments.measure:
        parser.error("give --arm, or --measure to size the work first")

    load()
    with connect(DatabaseConfig.from_environment()) as connection:
        tasks = rows(connection, arguments.limit)
        if arguments.pool_probe:
            queries, neighbours = (int(part) for part in arguments.pool_probe.split(":"))
            wanted = probe_examples(connection, queries, neighbours)
            tasks = [task for task in tasks if task["id"] in wanted]
    print(f"examples {len(tasks)}   encoder {arguments.encoder}")

    model = encoder(arguments.encoder)
    report = {"measured_at": datetime.now(UTC).isoformat(timespec="seconds")}

    if arguments.measure:
        for arm in ("after", "difference") if not arguments.arm else (arguments.arm,):
            measurement = run_measure(arm, model, tasks, arguments.measure)
            report[f"measure:{arm}"] = measurement
            print(
                f"  {arm:<11} {measurement['images_per_second']:6.2f} img/s   "
                f"dim {measurement['encoder']['dimension']}   "
                f"all {len(tasks)} -> {measurement['projected_minutes_for_all']} min"
            )

    if arguments.arm:
        name = arguments.name or f"{arguments.arm}-{arguments.encoder}"
        print(f"\n{name}: encoding {len(tasks)} examples")
        result = run_arm(arguments.arm, name, model, tasks)
        report[name] = result
        print(f"\nwrote {result['examples']} x {result['dimension']} to {result['path']}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.is_file() else {}
    existing.update(report)
    REPORT.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
