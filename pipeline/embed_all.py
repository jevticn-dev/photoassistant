"""Compute the two vectors the recommender searches (phase 2, tasks 8 and 9).

    uv run --project ml --extra embeddings python -m pipeline.embed_all --measure 64
    uv run --project ml python -m pipeline.embed_all --calibrate
    uv run --project ml --extra embeddings python -m pipeline.embed_all --content
    uv run --project ml python -m pipeline.embed_all --style

Four modes, because they need different things and run at different times.

``--measure``   how many images a second this machine encodes, on a small pile.
                Task 8 asks for this before the device is chosen: a projection
                from 64 images decides whether the WSL2+ROCm setup is worth
                building at all (notes §B48).
``--calibrate`` measure the scaling constants over a stratified sample of fitted
                edits and write them to ``reports/fingerprint_scaling.json``.
                Runs once, and the file is committed.
``--content``   CLIP over every "before" image into ``photos.clip_embedding``.
``--style``     the thirty-number fingerprint into ``examples.style_fingerprint``.

**Order matters, and not only for the obvious reason.** ``--style`` reads the
fitted recipe out of ``examples``, so it must run after fitting has settled —
including ``refit_worst``, which rewrites the recipes of the worst five percent.
Fingerprints computed before that would describe recipes that no longer exist,
and nothing would report it (notes §B43).

**Only ``--measure`` and ``--content`` need torch.** The other two never import it,
so they run in a plain library install.
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from photoassistant.embeddings import Scaling, raw_fingerprint
from photoassistant.embeddings.fingerprint import FINGERPRINT_DIMENSION
from photoassistant.schema import EditRecipe
from photoassistant.storage import (
    STEP_DERIVE_BEFORE,
    STEP_EMBED_CONTENT,
    DatabaseConfig,
    Manifest,
    ObjectStorageConfig,
    ObjectStore,
    connect,
    step_embed_style,
)
from PIL import Image

from pipeline.environment import REPOSITORY_ROOT, load

REPORTS = Path(__file__).parent / "reports"
SCALING_FILE = REPORTS / "fingerprint_scaling.json"

# Overridable so that a test run does not clobber the committed measurement. The
# restart test drives this module over five fixture rows; without the override it
# leaves behind a report that looks like a measurement and describes a fixture.
REPORT = Path(os.environ.get("EMBED_REPORT") or Path(__file__).parent / "embed_report.json")

_STORE: dict[str, ObjectStore] = {}


def store() -> ObjectStore:
    if "store" not in _STORE:
        _STORE["store"] = ObjectStore(ObjectStorageConfig.from_environment())
    return _STORE["store"]


def staging_dir() -> Path:
    return Path(os.environ.get("STAGING_DIR", REPOSITORY_ROOT / "pipeline/.work/staging"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        sys.exit(f"staging file missing: {path}. Run pipeline.parse_catalogue first.")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_image(key: str) -> np.ndarray:
    """One stored derivative as sRGB floats in [0, 1]."""
    data = store().get(store().derivatives, key)
    pixels = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float64)
    return pixels / 255.0


def restrict(items: list, arguments: argparse.Namespace, key) -> list:
    """Apply ``--only`` and ``--limit``, in that order.

    ``--only`` first: limiting a list and then filtering it would silently return
    fewer items than asked for, or none, depending on where the wanted references
    happened to sit.
    """
    if arguments.only:
        wanted = {name.strip() for name in arguments.only.split(",") if name.strip()}
        items = [item for item in items if key(item) in wanted]
    if arguments.limit:
        items = items[: arguments.limit]
    return items


def report_failures(failures: list[dict]) -> None:
    """Say out loud that some rows failed, rather than only in the JSON report.

    A pass that skips rows and prints only how many it wrote looks exactly like a
    pass that had nothing to do. This line, and the non-zero exit in ``main``,
    exist so that an unattended overnight run cannot be read as clean when it was
    not — the same silent-failure shape as notes §B50.
    """
    if not failures:
        return
    print(f"\n{len(failures)} FAILED:")
    for failure in failures[:10]:
        print(f"  {failure}")
    if len(failures) > 10:
        print(f"  ... and {len(failures) - 10} more; the rest are in the report")


def as_vector_literal(values: np.ndarray) -> str:
    """A pgvector literal, cast on the SQL side.

    Written as text rather than through the ``pgvector`` adapter package on
    purpose: the format is ``[1,2,3]`` and stable, and this keeps the pipeline's
    dependency list one package shorter for something that is three lines.
    """
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


# --------------------------------------------------------------------------- #
# Content: CLIP over the "before" images
# --------------------------------------------------------------------------- #


def content_references(connection) -> list[tuple[str, str]]:
    """Photographs still needing an embedding, as (reference, object key) pairs.

    The key comes out of ``photos.pre512_key`` rather than being rebuilt from the
    reference. The column exists to say where the object is, and deriving the same
    string a second time puts one convention in two places — which is fine until
    one of them changes. It also means a row may point anywhere, which is what
    lets the restart test borrow an existing derivative instead of uploading one.
    """
    tracker = Manifest(connection)
    have_before = tracker.done_references(STEP_DERIVE_BEFORE)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_reference, pre512_key FROM photos
             WHERE source = 'Fivek' AND pre512_key IS NOT NULL
             ORDER BY source_reference
            """
        )
        stored = dict(cursor.fetchall())

    available = [reference for reference in stored if reference in have_before]
    return [(reference, stored[reference]) for reference in
            tracker.pending_from(STEP_EMBED_CONTENT, available)]


def run_content(arguments: argparse.Namespace) -> dict:
    from photoassistant.embeddings.clip import ClipConfig, ClipEncoder

    config = ClipConfig.from_environment()
    if arguments.threads:
        config = ClipConfig(**{**vars(config), "threads": arguments.threads})

    database = DatabaseConfig.from_environment()
    with connect(database) as connection:
        Manifest(connection).reset_stale_running(STEP_EMBED_CONTENT)
        pending = content_references(connection)

    pending = restrict(pending, arguments, key=lambda pair: pair[0])

    print(f"photographs to embed: {len(pending)}")
    if not pending:
        return {"embedded": 0}

    encoder = ClipEncoder(config)
    print(f"encoder: {encoder.describe()}\n")

    began = time.perf_counter()
    embedded = 0
    failed: list[dict] = []

    # Transactional, not autocommit: the vector and the manifest mark are one
    # write. Separated, a crash between them leaves a step marked done with no
    # vector behind it, and every later run skips it (notes §B18).
    with connect(database, autocommit=False) as connection:
        tracker = Manifest(connection)
        for start in range(0, len(pending), config.batch_size):
            batch = pending[start : start + config.batch_size]

            claimed: list[tuple[str, str]] = []
            for reference, key in batch:
                if tracker.claim(reference, STEP_EMBED_CONTENT):
                    claimed.append((reference, key))
            connection.commit()
            if not claimed:
                continue

            try:
                images = [load_image(key) for _, key in claimed]
                vectors = encoder.encode(images)
            except Exception as error:  # noqa: BLE001 - one bad batch must not end the run
                for reference, _ in claimed:
                    tracker.fail(reference, STEP_EMBED_CONTENT, f"{type(error).__name__}: {error}")
                connection.commit()
                failed.append(
                    {"batch": claimed[0][0], "error": f"{type(error).__name__}: {error}"}
                )
                continue

            with connection.transaction(), connection.cursor() as cursor:
                for (reference, _), vector in zip(claimed, vectors, strict=True):
                    cursor.execute(
                        """
                        UPDATE photos SET clip_embedding = %s::vector
                         WHERE source = 'Fivek' AND source_reference = %s
                        """,
                        (as_vector_literal(vector), reference),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(f"no photos row for {reference}")
                    tracker.complete(reference, STEP_EMBED_CONTENT)

            embedded += len(claimed)
            if embedded % (config.batch_size * 10) < config.batch_size:
                rate = embedded / max(time.perf_counter() - began, 1e-9)
                left = (len(pending) - embedded) / max(rate, 1e-9) / 60.0
                print(f"  {embedded}/{len(pending)}  {rate:.1f} img/s  left ~{left:.0f} min")

    elapsed = time.perf_counter() - began
    print(f"\nembedded {embedded} in {elapsed / 60:.1f} min ({embedded / elapsed:.1f} img/s)")
    report_failures(failed)
    return {
        "embedded": embedded,
        "seconds": round(elapsed, 1),
        "images_per_second": round(embedded / elapsed, 2) if elapsed else None,
        "encoder": encoder.describe(),
        "failed": failed,
    }


def run_measure(arguments: argparse.Namespace) -> dict:
    """Throughput on a small pile, and what it projects to over the whole corpus."""
    from photoassistant.embeddings.clip import ClipConfig, ClipEncoder

    config = ClipConfig.from_environment()
    if arguments.threads:
        config = ClipConfig(**{**vars(config), "threads": arguments.threads})

    references = [row["reference"] for row in read_jsonl(staging_dir() / "photos.jsonl")]
    step = max(1, len(references) // arguments.measure)
    chosen = references[:: step][: arguments.measure]

    loading = time.perf_counter()
    encoder = ClipEncoder(config)
    load_seconds = time.perf_counter() - loading

    images = [load_image(f"fivek/{reference}/pre512.png") for reference in chosen]

    # A first batch is not representative: lazy allocations and cache warm-up land
    # on it. Measured after one throwaway batch, as the bandwidth measurement did.
    encoder.encode(images[: min(len(images), config.batch_size)])

    began = time.perf_counter()
    for start in range(0, len(images), config.batch_size):
        encoder.encode(images[start : start + config.batch_size])
    elapsed = time.perf_counter() - began

    rate = len(images) / elapsed
    projection = len(references) / rate / 60.0
    report = {
        "encoder": encoder.describe(),
        "weights_load_seconds": round(load_seconds, 1),
        "images": len(images),
        "seconds": round(elapsed, 2),
        "images_per_second": round(rate, 2),
        "corpus": len(references),
        "projected_minutes": round(projection, 1),
    }
    print(json.dumps(report, indent=2))
    print(
        f"\n{rate:.1f} img/s  ->  {len(references)} photographs in ~{projection:.0f} min "
        f"on {config.device}"
    )
    return report


# --------------------------------------------------------------------------- #
# Style: the thirty-number fingerprint
# --------------------------------------------------------------------------- #


def fitted_examples(connection, experts: str) -> list[dict]:
    """Every fitted example row, newest recipe included, grouped-friendly order.

    Ordered by photograph so that the "before" statistics can be computed once per
    photograph rather than once per expert — the same neutral image serves all
    five, which is a fivefold saving for free.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.source_reference, e.expert, e.id, e.edit, p.pre512_key, e.after_key
              FROM examples e
              JOIN photos p ON p.id = e.photo_id
             WHERE NOT e.excluded_from_fitting
               AND e.expert = ANY(%s)
               AND p.pre512_key IS NOT NULL
               AND e.after_key IS NOT NULL
             ORDER BY p.source_reference, e.expert
            """,
            (list(experts),),
        )
        return [
            {
                "reference": reference,
                "expert": expert,
                "id": str(identifier),
                "edit": edit if isinstance(edit, dict) else json.loads(edit),
                "before_key": before_key,
                "after_key": after_key,
            }
            for reference, expert, identifier, edit, before_key, after_key in cursor.fetchall()
        ]


def raw_for(row: dict, before_statistics: np.ndarray) -> np.ndarray:
    from photoassistant.embeddings.statistics import colour_statistics

    after = load_image(row["after_key"])
    difference = colour_statistics(after) - before_statistics
    return raw_fingerprint(EditRecipe.model_validate(row["edit"]), difference)


def group_by_reference(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["reference"], []).append(row)
    return list(grouped.items())


def run_calibrate(arguments: argparse.Namespace) -> dict:
    """Measure the scaling constants and write them where the style pass reads them.

    A stratified sample rather than the whole corpus: estimating a mean and a
    standard deviation from two thousand rows is accurate to well under a percent,
    and the alternative is a pass over 25.000 image pairs to produce thirty pairs
    of numbers.
    """
    # Imported here rather than at the top: pipeline.fit_all pins the BLAS thread
    # count to 1 at import time, which is right for eight fitting processes and
    # wrong for torch. This mode never touches torch, so the pin is harmless — but
    # it must not reach --content or --measure.
    from photoassistant.embeddings.statistics import colour_statistics

    from pipeline.fit_all import stratified

    database = DatabaseConfig.from_environment()
    with connect(database) as connection:
        rows = fitted_examples(connection, arguments.experts)

    if not rows:
        sys.exit("no fitted examples in the database — run pipeline.fit_all first")

    sample = stratified(rows, arguments.sample) if arguments.sample else rows
    print(f"fitted examples {len(rows)}, calibrating on {len(sample)}")

    began = time.perf_counter()
    vectors: list[np.ndarray] = []
    for index, (_, group) in enumerate(group_by_reference(sample), start=1):
        before = colour_statistics(load_image(group[0]["before_key"]))
        vectors.extend(raw_for(row, before) for row in group)
        if index % 100 == 0:
            print(f"  {len(vectors)}/{len(sample)}")

    scaling = Scaling.fit(np.array(vectors))
    scaling.save(
        SCALING_FILE,
        measured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        measured_over=len(vectors),
        experts=arguments.experts,
    )

    seconds = time.perf_counter() - began
    print(f"\nwrote {SCALING_FILE} from {len(vectors)} edits in {seconds:.0f} s")
    return {"calibrated_on": len(vectors), "file": str(SCALING_FILE)}


def run_style(arguments: argparse.Namespace) -> dict:
    from photoassistant.embeddings.statistics import colour_statistics

    if not SCALING_FILE.is_file():
        sys.exit(f"{SCALING_FILE} is missing. Run --calibrate first.")
    scaling = Scaling.load(SCALING_FILE)

    database = DatabaseConfig.from_environment()
    with connect(database) as connection:
        tracker = Manifest(connection)
        for expert in arguments.experts:
            tracker.reset_stale_running(step_embed_style(expert))
        done = {
            expert: tracker.done_references(step_embed_style(expert))
            for expert in arguments.experts
        }
        rows = fitted_examples(connection, arguments.experts)

    pending = [row for row in rows if row["reference"] not in done[row["expert"]]]
    pending = restrict(pending, arguments, key=lambda row: row["reference"])

    print(f"fitted examples {len(rows)}, fingerprints to compute {len(pending)}")
    if not pending:
        return {"written": 0}

    began = time.perf_counter()
    written = 0
    failures: list[dict] = []

    with connect(database, autocommit=False) as connection:
        tracker = Manifest(connection)
        for reference, group in group_by_reference(pending):
            claimed = [
                row
                for row in group
                if tracker.claim(reference, step_embed_style(row["expert"]))
            ]
            connection.commit()
            if not claimed:
                continue

            try:
                before = colour_statistics(load_image(claimed[0]["before_key"]))
            except Exception as error:  # noqa: BLE001
                for row in claimed:
                    tracker.fail(reference, step_embed_style(row["expert"]), str(error))
                connection.commit()
                failures.append({"reference": reference, "error": str(error)})
                continue

            for row in claimed:
                step = step_embed_style(row["expert"])
                try:
                    vector = scaling.apply(raw_for(row, before))
                except Exception as error:  # noqa: BLE001
                    tracker.fail(reference, step, f"{type(error).__name__}: {error}")
                    connection.commit()
                    failures.append({"reference": reference, "expert": row["expert"],
                                     "error": f"{type(error).__name__}: {error}"})
                    continue

                with connection.transaction(), connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE examples SET style_fingerprint = %s::vector WHERE id = %s",
                        (as_vector_literal(vector), row["id"]),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(f"no examples row {row['id']}")
                    tracker.complete(reference, step)
                written += 1

            if written % 500 < len(claimed):
                rate = written / max(time.perf_counter() - began, 1e-9)
                left = (len(pending) - written) / max(rate, 1e-9) / 60.0
                print(f"  {written}/{len(pending)}  {rate:.1f} /s  left ~{left:.0f} min")

    elapsed = time.perf_counter() - began
    print(f"\nwrote {written} fingerprints in {elapsed / 60:.1f} min")
    report_failures(failures)
    return {
        "written": written,
        "seconds": round(elapsed, 1),
        "dimension": FINGERPRINT_DIMENSION,
        "failures": failures,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--measure", type=int, default=0, metavar="N",
                        help="measure encoder throughput on N images and stop")
    parser.add_argument("--calibrate", action="store_true",
                        help="measure the fingerprint scaling constants and write them")
    parser.add_argument("--content", action="store_true", help="CLIP over the before images")
    parser.add_argument("--style", action="store_true", help="fingerprints over fitted examples")
    parser.add_argument("--experts", default="abcde")
    parser.add_argument("--sample", type=int, default=2000,
                        help="edits used by --calibrate; 0 uses all of them")
    parser.add_argument("--threads", type=int, default=0,
                        help="cap torch threads, for running alongside other work")
    parser.add_argument("--limit", type=int, default=0, metavar="N",
                        help="stop after N items; used by the restart test and for smoke runs")
    parser.add_argument("--only", default="", metavar="REFS",
                        help="comma-separated photograph references, for redoing a subset")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load()

    if not (arguments.measure or arguments.calibrate or arguments.content or arguments.style):
        sys.exit("pick a mode: --measure N, --calibrate, --content or --style")

    report: dict[str, dict] = {}
    if arguments.measure:
        report["measure"] = run_measure(arguments)
    if arguments.calibrate:
        report["calibrate"] = run_calibrate(arguments)
    if arguments.content:
        report["content"] = run_content(arguments)
    if arguments.style:
        report["style"] = run_style(arguments)

    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport: {REPORT}")

    # After the report is written, never before: a non-zero exit must not cost the
    # record of what happened.
    failed = sum(
        len(section.get("failures", section.get("failed", [])))
        for section in report.values()
    )
    if failed:
        sys.exit(f"{failed} items failed; see {REPORT}")


if __name__ == "__main__":
    main()
