"""Download the two renditions the probe compares against (phase 1b, ADR-16).

    uv run --project ml python pipeline/probe/fetch.py

For every photograph in ``sample.json``, fetches:

* ``tiff16_c`` — expert C's result, the "after" the fit aims at
* ``tiff16_inputAsShotZeroed`` — Lightroom's own neutral starting point

The second one is what makes the mentor's question answerable. ADR-4 has us
decode the DNG ourselves, so our "before" is not the one the expert started from;
without a baseline we could not tell a weak model apart from a different starting
point. Comparing against this rendition separates the two.

**Why these are kept rather than deleted after deriving.** ``.claude/rules/pipeline.md``
requires download-derive-delete in one step, because phase 2 moves roughly a
terabyte and cannot hold it. That rule is about scale. Here the whole set is a few
gigabytes, the derivation is still being written, and re-fetching on every change
would mean pulling it all again from a server MIT provides as a courtesy. The
files stay until the probe is finished; the production pipeline in phase 2 obeys
the rule as written.

Re-running is safe: a file already present at the size the server reports is
skipped, so an interrupted run resumes instead of starting over.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://data.csail.mit.edu/graphics/fivek/img"

SAMPLE = Path(__file__).parent / "sample.json"

# Path segment -> local folder. The segment is the catalogue's collection name;
# note the lower-case first letter, which the catalogue itself does not use.
RENDITIONS = {
    "expert": "tiff16_{expert}",
    "input": "tiff16_inputAsShotZeroed",
}

TIMEOUT_SECONDS = 300


def work_root() -> Path:
    """Where downloads land. Overridable, because 8 GB does not belong on every disk."""
    configured = os.environ.get("PROBE_WORK_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).parents[2] / "pipeline" / ".work"


def remote_size(url: str) -> int | None:
    """Content-Length without downloading, used to tell a complete file from a stump."""
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            length = response.headers.get("Content-Length")
            return int(length) if length else None
    except urllib.error.URLError:
        return None


def download(url: str, target: Path) -> tuple[bool, int]:
    """Fetch one file. Returns (whether it was downloaded now, bytes on disk).

    Writes to a temporary name and renames on success, so an interrupted run
    never leaves a half file that the size check would have to guess about.
    """
    expected = remote_size(url)

    if target.exists() and expected is not None and target.stat().st_size == expected:
        return False, target.stat().st_size

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")

    with (
        urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response,
        partial.open("wb") as out,
    ):
        while chunk := response.read(1 << 20):
            out.write(chunk)

    partial.replace(target)
    return True, target.stat().st_size


def main() -> None:
    if not SAMPLE.is_file():
        sys.exit(f"missing {SAMPLE} — run select_sample.py first")

    document = json.loads(SAMPLE.read_text(encoding="utf-8"))
    expert = document["expert"]
    photos = [entry["basename"] for entry in document["photos"]]

    root = work_root() / "tiff"
    print(f"{len(photos)} photographs x {len(RENDITIONS)} renditions -> {root}")

    fetched = skipped = failed = 0
    total_bytes = 0

    for index, basename in enumerate(photos, start=1):
        for kind, segment_template in RENDITIONS.items():
            segment = segment_template.format(expert=expert)
            url = f"{BASE_URL}/{segment}/{basename}.tif"
            target = root / kind / f"{basename}.tif"

            try:
                downloaded, size = download(url, target)
            except (urllib.error.URLError, OSError) as error:
                failed += 1
                print(f"  [{index:3d}/{len(photos)}] {kind:<6} {basename}  FAILED: {error}")
                continue

            total_bytes += size
            if downloaded:
                fetched += 1
                print(f"  [{index:3d}/{len(photos)}] {kind:<6} {basename}  {size / 1048576:.1f} MB")
            else:
                skipped += 1

    print()
    print(f"downloaded {fetched}, already present {skipped}, failed {failed}")
    print(f"total on disk: {total_bytes / 1073741824:.2f} GB")

    if failed:
        sys.exit(f"{failed} downloads failed; re-run to retry only those")


if __name__ == "__main__":
    main()
