"""Fetch every FiveK rendition, derive what we keep, and throw the original away.

    uv run --project ml python -m pipeline.fetch_derive
    uv run --project ml python -m pipeline.fetch_derive --limit 200 --experts c

Run as a module, not as a path. ``python pipeline/fetch_derive.py`` puts
``pipeline/`` on the import path instead of the repository root, and the package
imports then fail; ``-m`` from the repository root resolves them, and is also what
lets a spawned derive process re-import this module by name.

The long pole of phase 2: roughly 1.58 TB crosses the network, of which about
12 GB is kept. It runs for hours, it will be interrupted, and it has to be safe to
start again — so every unit of work is one manifest step, and the manifest is the
only thing that decides what still needs doing.

**One step, not three.** Fetching a file, deriving from it and deleting it are a
single manifest step on purpose. As three steps, a crash after the first leaves
hundreds of gigabytes of temporary files that no restart will clean up, because
as far as the manifest is concerned the fetch finished
(`docs/notes/phase-2-concepts.md` §B18).

**Two pools, because they are two different waits.** Measured 2026-08-28:
downloading gives about one file per second at six connections, and turning one
file into derivatives takes 1.08 s. They are the same speed, which is the worst
case for guessing — done in sequence the run takes twice as long as it needs to.
Downloads therefore run in threads, which cost nothing while waiting on the
network, and derivation in separate processes, because it is arithmetic and
threads in Python do not run arithmetic in parallel. See §B21.

Disk stays bounded without any bookkeeping: a download thread holds exactly one
temporary file and does not start another until that file has been derived and
deleted, so the ceiling is the number of download workers times one rendition.

**Order is a stride, not alphabetical.** The names are grouped by photographer, so
taking them in order would mean the first thousand finished photographs all come
from the same few cameras and scenes. The calibration pass over ~1000 edits starts
as soon as enough have landed, and it has to be representative when it does.
"""

import os

# Set before anything imports NumPy: each derive process would otherwise start a
# BLAS thread pool sized to the whole machine, and four processes times sixteen
# threads on eight cores is slower than doing it serially. Child processes are
# spawned on Windows and inherit this environment, so setting it here covers them.
for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import tifffile  # noqa: E402
from photoassistant.imaging import make_derivatives  # noqa: E402
from photoassistant.storage import (  # noqa: E402
    STEP_DERIVE_BEFORE,
    DatabaseConfig,
    Manifest,
    ObjectStorageConfig,
    ObjectStore,
    connect,
    step_derive_after,
)

from pipeline.environment import REPOSITORY_ROOT, load  # noqa: E402

BASE_URL = "https://data.csail.mit.edu/graphics/fivek/img"

BEFORE_RENDITION = "tiff16_inputAsShotZeroed"

ALL_EXPERTS = ("a", "b", "c", "d", "e")

INDEX_FILES = ("filesAdobe.txt", "filesAdobeMIT.txt")

# Measured working point (pipeline/bandwidth_report.json): 50.86 MB/s at six
# connections against 14.94 sequential. Not raised further on purpose — the
# server is MIT's and shares this dataset as a courtesy.
DEFAULT_DOWNLOAD_WORKERS = 6

DEFAULT_DERIVE_WORKERS = max(1, (os.cpu_count() or 4) // 2)

TIMEOUT_SECONDS = 600

# Attempts per file, with a widening pause between them. The server is somebody
# else's and a run lasts hours; a transient failure must not cost a photograph.
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 5.0

REPORT = Path(__file__).parent / "fetch_report.json"


@dataclass(frozen=True)
class WorkItem:
    """One manifest step: one rendition, its derivatives, and where they go."""

    reference: str
    expert: str | None
    step: str
    url: str
    keys: dict[str, str]
    with_proxy: bool


def read_basenames(dataset: Path) -> list[str]:
    """The 5000 photograph names, from the two index files that also name two licences."""
    names: set[str] = set()
    for index in INDEX_FILES:
        path = dataset / index
        if not path.is_file():
            sys.exit(f"index file missing: {path}")
        names.update(line.strip() for line in path.read_text().splitlines() if line.strip())
    return sorted(names)


def strided(names: list[str]) -> list[str]:
    """Reorder so that any prefix of the result is spread over the whole catalogue.

    Stepping by a number coprime with the length visits every entry exactly once
    while never staying in one neighbourhood — the same reason the probe chose a
    stride over a seeded shuffle: it is reproducible against nothing but the input
    list, and anyone can check it by hand.
    """
    count = len(names)
    if count < 2:
        return list(names)

    stride = 2999 if count % 2999 else 2971
    return [names[(index * stride) % count] for index in range(count)]


def plan(basenames: list[str], experts: tuple[str, ...]) -> list[WorkItem]:
    """Every step that would have to run for a full pass, in the order to attempt it.

    The "before" rendition comes first for each photograph. It is the one a fit
    cannot do without, and it is shared by all five experts, so having it early
    is what lets fitting start while the rest is still arriving.
    """
    items: list[WorkItem] = []
    for reference in strided(basenames):
        items.append(
            WorkItem(
                reference=reference,
                expert=None,
                step=STEP_DERIVE_BEFORE,
                url=f"{BASE_URL}/{BEFORE_RENDITION}/{reference}.tif",
                keys={
                    "fit": f"fivek/{reference}/pre512.png",
                    "proxy": f"fivek/{reference}/proxy2048.jpg",
                },
                with_proxy=True,
            )
        )
        for expert in experts:
            items.append(
                WorkItem(
                    reference=reference,
                    expert=expert,
                    step=step_derive_after(expert),
                    url=f"{BASE_URL}/tiff16_{expert}/{reference}.tif",
                    keys={"fit": f"fivek/{reference}/after512-{expert}.png"},
                    with_proxy=False,
                )
            )
    return items


def derive_in_process(path: str, with_proxy: bool) -> dict[str, object]:
    """Read one rendition and return the encoded derivatives. Runs in a subprocess.

    It returns **bytes**, not arrays, and the reason is smaller than it looks.
    Measured on this machine: a 60 MB rendition costs 41 ms to cross a process
    boundary, the encoded derivatives 1 ms, and the same object costs nothing at
    all between threads because they share memory. Against 1080 ms of derivation
    that is a saving of about 4% — worth taking, but not what makes the split
    worth making. The split is worth making because of the GIL; this only avoids
    paying an avoidable toll on top of it.

    The stronger argument is memory. Returning arrays would leave one 60 MB
    rendition resident per in-flight item, so six download workers would hold
    360 MB of decoded image for no reason.

    ``tifffile``, never Pillow: Pillow reads a 16-bit TIFF as 8-bit without a
    word, and 75% of pixels lose their low byte (`.claude/rules/pipeline.md`).
    """
    rendition = tifffile.imread(path)
    result = make_derivatives(rendition, with_proxy=with_proxy)

    payload: dict[str, object] = {
        "fit": result.fit.data,
        "fit_content_type": result.fit.content_type,
        "fit_size": (result.fit.width, result.fit.height),
        "gamut_fraction": result.gamut_fraction,
        "source_size": (int(rendition.shape[1]), int(rendition.shape[0])),
    }
    if result.proxy is not None:
        payload["proxy"] = result.proxy.data
        payload["proxy_content_type"] = result.proxy.content_type
        payload["proxy_size"] = (result.proxy.width, result.proxy.height)
    return payload


def download(url: str, destination: Path) -> int:
    """Fetch one file, retrying transient failures. Returns the byte count.

    A partial file is not resumed even though the server supports ranges. The step
    is atomic anyway — an interrupted download is discarded and the whole step
    runs again — and resuming would add a second way for a truncated file to reach
    the decoder.
    """
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                written = 0
                with destination.open("wb") as handle:
                    while chunk := response.read(1 << 20):
                        handle.write(chunk)
                        written += len(chunk)
                return written
        except urllib.error.HTTPError as error:
            # A 404 is data, not weather: that rendition does not exist, and
            # asking four times will not change it.
            if error.code == 404:
                raise
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error

        destination.unlink(missing_ok=True)
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(BACKOFF_SECONDS * (attempt + 1))

    raise RuntimeError(f"{MAX_ATTEMPTS} attempts failed for {url}: {last_error}")


class Runner:
    """Holds what the worker threads share and does one item at a time."""

    def __init__(
        self,
        *,
        database: DatabaseConfig,
        store: ObjectStore,
        derive_pool: ProcessPoolExecutor,
        work_dir: Path,
    ) -> None:
        self._database = database
        self._store = store
        self._derive_pool = derive_pool
        self._work_dir = work_dir
        # One connection per thread rather than one shared. psycopg serialises
        # concurrent use of a single connection, which would quietly turn six
        # workers into one at every manifest write.
        self._local = threading.local()

    def manifest(self) -> Manifest:
        existing = getattr(self._local, "manifest", None)
        if existing is None:
            existing = Manifest(connect(self._database))
            self._local.manifest = existing
        return existing

    def run(self, item: WorkItem) -> dict[str, object]:
        """Claim, fetch, derive, upload, delete, mark. In that order, always."""
        tracker = self.manifest()
        if not tracker.claim(item.reference, item.step):
            return {"reference": item.reference, "step": item.step, "outcome": "skipped"}

        temporary = self._work_dir / f"{item.reference}.{item.step.replace(':', '-')}.tif"
        began = time.perf_counter()
        try:
            downloaded = download(item.url, temporary)
            derived = self._derive_pool.submit(
                derive_in_process, str(temporary), item.with_proxy
            ).result()

            self._store.put(
                self._store.derivatives,
                item.keys["fit"],
                derived["fit"],
                str(derived["fit_content_type"]),
            )
            if item.with_proxy and "proxy" in derived:
                self._store.put(
                    self._store.derivatives,
                    item.keys["proxy"],
                    derived["proxy"],
                    str(derived["proxy_content_type"]),
                )
        except Exception as error:  # noqa: BLE001 - one bad file must not end the run
            tracker.fail(item.reference, item.step, f"{type(error).__name__}: {error}")
            return {
                "reference": item.reference,
                "step": item.step,
                "outcome": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
        finally:
            # Before the manifest is marked, and on every path out. This is the
            # deletion half of "fetch, derive, delete in one step".
            temporary.unlink(missing_ok=True)

        # Only now. Everything this step promises is durably stored.
        tracker.complete(item.reference, item.step)
        return {
            "reference": item.reference,
            "step": item.step,
            "outcome": "done",
            "bytes": downloaded,
            "seconds": round(time.perf_counter() - began, 2),
            "gamut_fraction": round(float(derived["gamut_fraction"]), 6),
        }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--experts",
        default="".join(ALL_EXPERTS),
        help="which experts to fetch, e.g. 'c' or 'abcde' (default: all five)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="stop after this many photographs; 0 means all of them",
    )
    parser.add_argument(
        "--download-workers",
        type=int,
        default=int(os.environ.get("INGEST_DOWNLOAD_WORKERS", DEFAULT_DOWNLOAD_WORKERS)),
    )
    parser.add_argument(
        "--derive-workers",
        type=int,
        default=int(os.environ.get("INGEST_DERIVE_WORKERS", DEFAULT_DERIVE_WORKERS)),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what is outstanding and exit without fetching anything",
    )
    return parser.parse_args()


def outstanding(items: list[WorkItem], tracker: Manifest) -> list[WorkItem]:
    """Drop what the manifest already calls done, one query per distinct step."""
    done_by_step = {step: tracker.done_references(step) for step in {item.step for item in items}}
    return [item for item in items if item.reference not in done_by_step[item.step]]


def main() -> None:
    arguments = parse_arguments()
    load()

    dataset = Path(os.environ.get("FIVEK_DATASET_PATH", ""))
    if not dataset.is_dir():
        sys.exit("FIVEK_DATASET_PATH is not set or does not point at a directory")

    experts = tuple(character for character in arguments.experts if character in ALL_EXPERTS)
    if not experts:
        sys.exit(f"no valid experts in {arguments.experts!r}; choose from {ALL_EXPERTS}")

    basenames = read_basenames(dataset)
    if arguments.limit:
        basenames = strided(basenames)[: arguments.limit]

    items = plan(basenames, experts)

    database = DatabaseConfig.from_environment()
    store = ObjectStore(ObjectStorageConfig.from_environment())
    store.ensure_buckets()

    with connect(database) as startup:
        tracker = Manifest(startup)
        # Before any worker starts, and from this one process. A previous run
        # that died left its in-flight steps marked Running, and claim() refuses
        # those on purpose — without this they would be skipped forever (§B18).
        recovered = sum(
            tracker.reset_stale_running(step) for step in {item.step for item in items}
        )
        pending = outstanding(items, tracker)

    print(f"photographs {len(basenames)}  experts {''.join(experts)}")
    print(f"steps total {len(items)}  outstanding {len(pending)}  recovered {recovered}")

    if arguments.dry_run or not pending:
        print("nothing to do" if not pending else "dry run: stopping here")
        return

    work_dir = Path(os.environ.get("INGEST_WORK_DIR", REPOSITORY_ROOT / "pipeline/.work/ingest"))
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"downloads {arguments.download_workers}  derives {arguments.derive_workers}")
    print(f"scratch {work_dir}\n")

    results: list[dict[str, object]] = []
    began = time.perf_counter()

    with ProcessPoolExecutor(max_workers=arguments.derive_workers) as derive_pool:
        runner = Runner(
            database=database, store=store, derive_pool=derive_pool, work_dir=work_dir
        )
        with ThreadPoolExecutor(max_workers=arguments.download_workers) as download_pool:
            futures = [download_pool.submit(runner.run, item) for item in pending]
            for finished, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                results.append(result)
                if result["outcome"] == "failed":
                    print(f"  FAILED {result['reference']} {result['step']}: {result['error']}")
                if finished % 50 == 0 or finished == len(futures):
                    _report_progress(finished, len(futures), results, began)

    write_report(results, time.perf_counter() - began, arguments)


def _report_progress(
    finished: int, total: int, results: list[dict[str, object]], began: float
) -> None:
    elapsed = time.perf_counter() - began
    transferred = sum(int(r.get("bytes", 0)) for r in results)
    rate = transferred / 1e6 / elapsed if elapsed > 0 else 0.0
    remaining = (total - finished) * elapsed / finished if finished else 0.0
    print(
        f"  {finished}/{total}  {rate:.1f} MB/s  "
        f"{transferred / 1e9:.1f} GB  elapsed {elapsed / 60:.0f} min  "
        f"left ~{remaining / 3600:.1f} h"
    )


def write_report(
    results: list[dict[str, object]], elapsed: float, arguments: argparse.Namespace
) -> None:
    done = [r for r in results if r["outcome"] == "done"]
    failed = [r for r in results if r["outcome"] == "failed"]
    transferred = sum(int(r.get("bytes", 0)) for r in done)
    gamut = sorted(float(r["gamut_fraction"]) for r in done)

    report = {
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "experts": arguments.experts,
        "steps_done": len(done),
        "steps_failed": len(failed),
        "steps_skipped": len([r for r in results if r["outcome"] == "skipped"]),
        "gigabytes_transferred": round(transferred / 1e9, 2),
        "hours": round(elapsed / 3600, 3),
        "megabytes_per_second": round(transferred / 1e6 / elapsed, 2) if elapsed > 0 else 0.0,
        # ADR-17 requires this next to the fitting error rather than inside it:
        # a photograph with saturated colour outside sRGB has an error floor that
        # has nothing to do with our model.
        "gamut_fraction": {
            "median": round(gamut[len(gamut) // 2], 4) if gamut else None,
            "p90": round(gamut[int(len(gamut) * 0.9)], 4) if gamut else None,
            "max": round(gamut[-1], 4) if gamut else None,
        },
        "failures": [
            {"reference": r["reference"], "step": r["step"], "error": r["error"]} for r in failed
        ][:100],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\ndone {len(done)}  failed {len(failed)}")
    print(f"{report['gigabytes_transferred']} GB in {report['hours']} h "
          f"at {report['megabytes_per_second']} MB/s")
    print(f"written: {REPORT}")


if __name__ == "__main__":
    # Required on Windows, where a spawned derive process re-imports this module:
    # without the guard it would run main() again and fork a pool of its own,
    # recursively.
    main()
