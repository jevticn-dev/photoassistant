"""A local copy of the derivatives the evaluation reads over and over.

The exam runs the same 500 photographs through fifteen configurations. Each one
needs the neutral rendition and five expert results, so without a cache the same
3.000 objects cross the network fifteen times for a corpus that fits in about a
gigabyte of disk.

Phase 2 measured the cost of reading images out of storage rather than guessing
it: a pass that projected to 2,1 minutes from encoder throughput alone took 6,4,
because loading dominated (§B48). The same trap applies here, and the fix is
cheaper: read once, keep the bytes.

**Nothing here is authoritative.** Every file is a copy of an object that still
lives in MinIO, so the directory can be deleted at any time and the next run
refills it. That is why it sits under ``pipeline/.work`` with the rest of the
scratch space and never in git.
"""

import os
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from photoassistant.storage import ObjectStorageConfig, ObjectStore
from PIL import Image

from pipeline.environment import REPOSITORY_ROOT

DEFAULT_ROOT = REPOSITORY_ROOT / "pipeline/.work/eval-cache"

# One store per process, built on first use. A boto3 client cannot be pickled
# across a process boundary, so each worker makes its own rather than receiving
# one — the same pattern embed_all uses.
_STORE: dict[str, ObjectStore] = {}


def store() -> ObjectStore:
    if "store" not in _STORE:
        _STORE["store"] = ObjectStore(ObjectStorageConfig.from_environment())
    return _STORE["store"]


def cache_root() -> Path:
    return Path(os.environ.get("EVAL_CACHE_DIR") or DEFAULT_ROOT)


def local_path(key: str) -> Path:
    """Where a stored object lives locally. Mirrors the key, so it stays readable.

    Object keys are produced by this project (``fivek/<reference>/after512-a.png``)
    rather than by a user, so mirroring them into directories is safe; a key from
    outside would need sanitising first.
    """
    return cache_root() / key


def fetch(key: str) -> Path:
    """Return the local file for ``key``, downloading it once if it is missing.

    Written to a temporary name and then renamed, because a run interrupted
    mid-download would otherwise leave a truncated PNG that every later run would
    happily reuse — the same "mark it done only after it is done" rule the phase 2
    manifest follows (§B18), at file scale.
    """
    path = local_path(key)
    if path.is_file():
        return path

    data = store().get(store().derivatives, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(path)
    return path


def image(key: str) -> NDArray[np.float64]:
    """One derivative as sRGB floats in [0, 1], the shape the renderer works in."""
    with Image.open(fetch(key)) as handle:
        pixels = np.asarray(handle.convert("RGB"), dtype=np.float64)
    return pixels / 255.0
