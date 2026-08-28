"""Measure how fast the FiveK renditions actually download (phase 2, task 1).

    uv run --project ml python pipeline/measure_bandwidth.py

Phase 2 moves either ~519 GB (one expert) or ~1.58 TB (all five) across the
network. Which of those is affordable depends on a number nobody has measured:
the throughput this server gives us, and how much of it parallel connections
recover. The probe downloaded 200 files without timing any of them, and
``probe/fetch.py`` is strictly sequential, so both questions are open.

This script answers them before the plan commits to a number, and it is
**committed** for the same reason ``probe/sample.json`` is: a measurement whose
input cannot be reproduced is not a measurement.

**What it does.** For each concurrency level it downloads a fixed set of distinct
files and divides total bytes by wall-clock time. The bytes are counted and
thrown away — nothing is written to disk. That keeps a slow disk from being
measured instead of the network, and it costs at most a few gigabytes of
somebody else's bandwidth rather than the terabyte the real run will take.

**Why the levels stop at 6.** The server belongs to MIT and serves this dataset
as a courtesy to researchers (`.claude/rules/pipeline.md`). The question is where
parallelism stops helping, not how much the server will tolerate. If throughput
already saturates at 2, that is the answer.

**Why level 1 runs twice.** Network conditions drift, and the levels run one after
another, so a link that happens to be faster early would make sequential look
good for a reason that has nothing to do with concurrency. The repeat at the end
is a control: if the two sequential numbers disagree, the comparison between
levels is not trustworthy and the whole run should be repeated. This is the same
device ADR-19 used to tell a real fix apart from an artefact.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE_URL = "https://data.csail.mit.edu/graphics/fivek/img"

# One rendition for every level, so the levels are comparable. Expert C is the
# probe's expert and the usual choice in the FiveK literature.
RENDITION = "tiff16_c"

# The two index files that together name all 5000 photographs. They are also two
# licences, but that does not matter here: nothing is kept.
INDEX_FILES = ("filesAdobe.txt", "filesAdobeMIT.txt")

# Concurrency levels, in the order they run. The trailing 1 is the control.
LEVELS: tuple[int, ...] = (1, 2, 4, 6, 1)

# Per level, whichever limit is reached first. The file cap bounds the download
# on a fast link (12 files is roughly 600 MB), the time cap bounds the wait on a
# slow one. Together they keep the whole run under about ten minutes and under
# about three gigabytes.
FILES_PER_LEVEL = 12
SECONDS_PER_LEVEL = 90.0

TIMEOUT_SECONDS = 300

REPORT = Path(__file__).parent / "bandwidth_report.json"

# Sizes measured over 150 photographs while phase 2 was being planned. Used only
# to turn a measured rate into an estimated duration.
MB_PER_EXPERT_RENDITION = 52.9
MB_PER_INPUT_RENDITION = 50.9
PHOTO_COUNT = 5000


def dataset_root() -> Path:
    """The dataset path comes from the environment, never from the source."""
    raw = os.environ.get("FIVEK_DATASET_PATH")
    if not raw:
        sys.exit("FIVEK_DATASET_PATH is not set. Export it or pass it inline.")
    root = Path(raw)
    if not root.is_dir():
        sys.exit(f"FIVEK_DATASET_PATH does not point at a directory: {root}")
    return root


def all_basenames(dataset: Path) -> list[str]:
    """Every photograph name, sorted, from the two index files."""
    names: set[str] = set()
    for index in INDEX_FILES:
        path = dataset / index
        if not path.is_file():
            sys.exit(f"Index file missing: {path}")
        names.update(line.strip() for line in path.read_text().splitlines() if line.strip())
    return sorted(names)


def files_for_levels(basenames: list[str]) -> list[list[str]]:
    """A distinct set of files per level, spread across the whole catalogue.

    Distinct because a file fetched twice could come back from a cache — either
    the server's or something in between — and a cached file measures the cache,
    not the link. Spread by stride rather than taken from the front so that one
    photographer's habitually huge files cannot land entirely in one level.
    """
    needed = FILES_PER_LEVEL * len(LEVELS)
    if len(basenames) < needed:
        sys.exit(f"Need {needed} distinct files, catalogue has {len(basenames)}")
    stride = len(basenames) // needed
    picked = [basenames[i * stride] for i in range(needed)]
    return [picked[i * FILES_PER_LEVEL : (i + 1) * FILES_PER_LEVEL] for i in range(len(LEVELS))]


def url_for(basename: str) -> str:
    return f"{BASE_URL}/{RENDITION}/{basename}.tif"


def server_facts(basename: str) -> dict[str, object]:
    """One HEAD request, for facts the real fetcher will want to rely on.

    ``Accept-Ranges: bytes`` decides whether an interrupted download can resume
    from where it stopped or has to start over — the difference between losing
    seconds and losing a 50 MB file.
    """
    request = urllib.request.Request(url_for(basename), method="HEAD")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return {
            "server": response.headers.get("Server"),
            "accept_ranges": response.headers.get("Accept-Ranges"),
            "content_length": int(response.headers["Content-Length"]),
            "content_type": response.headers.get("Content-Type"),
        }


def download_and_discard(basename: str) -> dict[str, object]:
    """Read one file to the end, counting bytes, keeping none of them."""
    began = time.perf_counter()
    total = 0
    try:
        with urllib.request.urlopen(url_for(basename), timeout=TIMEOUT_SECONDS) as response:
            while chunk := response.read(1 << 20):
                total += len(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "basename": basename,
            "bytes": total,
            "seconds": time.perf_counter() - began,
            "error": f"{type(error).__name__}: {error}",
        }
    return {
        "basename": basename,
        "bytes": total,
        "seconds": time.perf_counter() - began,
        "error": None,
    }


def run_level(concurrency: int, basenames: list[str]) -> dict[str, object]:
    """Download the level's files at the given concurrency and time the whole thing.

    The rate is total bytes over total wall time, not the average of per-file
    rates: with several connections open at once those overlap, and averaging
    them would count the same seconds more than once.
    """
    deadline = time.perf_counter() + SECONDS_PER_LEVEL
    results: list[dict[str, object]] = []

    def guarded(basename: str) -> dict[str, object] | None:
        # Checked per file rather than mid-transfer: a file cut in half would
        # contribute bytes without contributing the time they cost.
        if time.perf_counter() > deadline:
            return None
        return download_and_discard(basename)

    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for result in pool.map(guarded, basenames):
            if result is not None:
                results.append(result)
    elapsed = time.perf_counter() - began

    downloaded = sum(int(r["bytes"]) for r in results)
    failures = [r for r in results if r["error"]]
    per_file = sorted(
        float(r["bytes"]) / 1e6 / float(r["seconds"])
        for r in results
        if not r["error"] and float(r["seconds"]) > 0
    )

    return {
        "concurrency": concurrency,
        "files_attempted": len(results),
        "files_failed": len(failures),
        "megabytes": round(downloaded / 1e6, 1),
        "seconds": round(elapsed, 2),
        "megabytes_per_second": round(downloaded / 1e6 / elapsed, 2) if elapsed > 0 else 0.0,
        "per_file_mbps_median": round(per_file[len(per_file) // 2], 2) if per_file else None,
        "errors": [r["error"] for r in failures],
    }


def projection(mb_per_second: float) -> dict[str, object]:
    """Turn a measured rate into the two durations decision C is chosen between.

    One "before" rendition per photograph plus one "after" per expert — not two
    per edit, which double-counts the shared before image. See
    docs/notes/phase-2-concepts.md B17.
    """

    def hours(experts: int) -> float:
        total_mb = PHOTO_COUNT * (MB_PER_INPUT_RENDITION + experts * MB_PER_EXPERT_RENDITION)
        return total_mb / mb_per_second / 3600

    return {
        "megabytes_per_second": round(mb_per_second, 2),
        "one_expert_gigabytes": round(PHOTO_COUNT * (MB_PER_INPUT_RENDITION + 52.9) / 1000, 1),
        "one_expert_hours": round(hours(1), 1),
        "five_experts_gigabytes": round(
            PHOTO_COUNT * (MB_PER_INPUT_RENDITION + 5 * MB_PER_EXPERT_RENDITION) / 1000, 1
        ),
        "five_experts_hours": round(hours(5), 1),
    }


def main() -> None:
    dataset = dataset_root()
    basenames = all_basenames(dataset)
    per_level = files_for_levels(basenames)

    facts = server_facts(basenames[0])
    print(f"server: {facts['server']}  accept-ranges: {facts['accept_ranges']}")
    print(f"levels: {LEVELS}  files/level: {FILES_PER_LEVEL}  cap: {SECONDS_PER_LEVEL:.0f}s\n")

    levels: list[dict[str, object]] = []
    for concurrency, files in zip(LEVELS, per_level, strict=True):
        print(f"concurrency {concurrency} ...", end=" ", flush=True)
        measured = run_level(concurrency, files)
        levels.append(measured)
        print(
            f"{measured['megabytes_per_second']} MB/s "
            f"({measured['megabytes']} MB in {measured['seconds']}s, "
            f"{measured['files_failed']} failed)"
        )

    # The control: first and last level both ran at concurrency 1.
    first, last = levels[0], levels[-1]
    rates = [float(first["megabytes_per_second"]), float(last["megabytes_per_second"])]
    drift = abs(rates[0] - rates[1]) / max(rates) if max(rates) > 0 else 0.0

    best = max(levels, key=lambda level: float(level["megabytes_per_second"]))

    report = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rendition": RENDITION,
        "server": facts,
        "files_per_level": FILES_PER_LEVEL,
        "seconds_per_level": SECONDS_PER_LEVEL,
        "levels": levels,
        "control": {
            "sequential_first_mbps": rates[0],
            "sequential_last_mbps": rates[1],
            "relative_drift": round(drift, 3),
            "trustworthy": drift < 0.25,
        },
        "best_level": best["concurrency"],
        "projection_at_best": projection(float(best["megabytes_per_second"])),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\ncontrol: sequential {rates[0]} then {rates[1]} MB/s, drift {drift:.1%}")
    if not report["control"]["trustworthy"]:
        print("  the link moved during the run — treat the comparison as unreliable")
    projected = report["projection_at_best"]
    print(f"best: concurrency {best['concurrency']} at {best['megabytes_per_second']} MB/s")
    print(f"  one expert  {projected['one_expert_gigabytes']} GB  ~{projected['one_expert_hours']} h")
    print(
        f"  five experts {projected['five_experts_gigabytes']} GB "
        f"~{projected['five_experts_hours']} h"
    )
    print(f"\nwritten: {REPORT}")


if __name__ == "__main__":
    main()
