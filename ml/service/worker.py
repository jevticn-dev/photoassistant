"""The export worker: one loop, polling the ``jobs`` table (ADR-7, decision F).

**Inside this service rather than beside it.** Plan §9 says "the API writes, the
ML worker polls, the frontend asks for status". That worker is a process that
polls a table, and it is no less that for running in this container: it needs the
renderer, the schema and object storage, which is exactly what this image already
holds. A second container would be a second copy of a two-gigabyte image to run
one loop.

**The render does not run on the event loop.** It is NumPy over tens of
megapixels and takes seconds — twelve of them at 48 megapixels. Left on the loop
it would stop ``/health`` answering, and compose would restart the container in
the middle of the export it was doing. ``asyncio.to_thread`` puts it on a worker
thread, where NumPy releases the GIL for the array operations anyway.

**This worker knows nothing about users.** It takes a job that names an object
and a recipe, and writes an object. Who was allowed to ask was decided by the
.NET API before the row existed (`.claude/rules/ml_service.md`).
"""

import asyncio
import contextlib
import io
import json
import logging
from datetime import timedelta
from typing import Any

import numpy as np
from botocore.exceptions import ClientError
from PIL import Image, ImageOps, UnidentifiedImageError

from photoassistant.imaging import encode_png_quantised, render_full_resolution
from photoassistant.schema import EditRecipe, from_json
from photoassistant.storage import (
    DatabaseConfig,
    ObjectStorageConfig,
    ObjectStore,
    claim_next,
    connection,
    mark_done,
    mark_failed,
    reclaim_stale,
)

logger = logging.getLogger(__name__)


IDLE_SECONDS = 1.0
"""How long to wait after finding nothing.

An export takes seconds and a person is watching a progress line, so a poll per
second is the right order — long enough that an idle service is not asking a
question sixty times a minute, short enough that nobody notices the wait.
"""

STALE_AFTER = timedelta(minutes=15)
"""How old a ``Running`` job must be, at startup, to count as abandoned.

Only consulted while starting, when nothing of ours is running by definition.
Comfortably longer than the slowest export measured (twelve seconds), so the
only rows it can reach are ones a killed process left behind.
"""


def _status_of(error: ClientError) -> int:
    """HTTP status behind a botocore error, or 0 when it carries none."""
    return int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))


class ExportFailed(Exception):
    """Something about this job cannot be done, and saying so is the outcome.

    Distinct from an unexpected error: the message reaches the person who asked
    for the export, so it describes their situation rather than our insides.
    """


def _decode(payload: bytes) -> np.ndarray:
    """The original as an upright 8-bit sRGB array.

    ``exif_transpose`` for the same reason the derivatives route applies it: a
    camera held sideways writes the pixels in sensor order and records the
    rotation in a tag. The proxy the editor showed was made upright, so an export
    that skipped this would hand back a photograph lying on its side — after the
    person had judged it standing up.
    """
    try:
        with Image.open(io.BytesIO(payload)) as handle:
            handle.load()
            upright = ImageOps.exif_transpose(handle)

            return np.asarray(upright.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ExportFailed("the stored original could not be read as an image") from error


def render_export(original: bytes, recipe: EditRecipe) -> tuple[bytes, int, int]:
    """The finished file: bytes, width, height.

    **PNG, and losslessly** (§B120). JPEG at quality 95 moves 0.4% of pixels by
    more than dE 3 and even quality 100 reaches a worst pixel of 5.3, against a
    renderer proven to agree with the browser's to 0.108. The export is where the
    work leaves the system, so it leaves as the pixels that were computed.
    """
    pixels = _decode(original)
    rendered = render_full_resolution(pixels, recipe)
    encoded = encode_png_quantised(rendered)

    return encoded.data, encoded.width, encoded.height


async def _run_job(
    job_id: str,
    payload: dict[str, Any],
    store: ObjectStore,
) -> dict[str, Any]:
    original_key = payload.get("originalKey")
    document = payload.get("recipe")

    if not isinstance(original_key, str) or not original_key:
        raise ExportFailed("the job names no original to render")
    if not isinstance(document, dict):
        raise ExportFailed("the job carries no recipe")

    # Validated here as well as by the API. The service does not depend on
    # someone else's validation — the same rule the upload routes follow.
    #
    # Through `from_json` rather than `model_validate`: a stored document has to
    # declare its schema version, and only this path enforces that. The model
    # defaults it, which is right for a recipe written in code and wrong for one
    # that arrived from somewhere.
    try:
        recipe = from_json(json.dumps(document))
    except ValueError as error:
        raise ExportFailed("the job carries a recipe the schema refuses") from error

    try:
        original = await asyncio.to_thread(store.get, store.originals, original_key)
    except ClientError as error:
        if _status_of(error) in (403, 404):
            raise ExportFailed(
                "the original this project was made from is no longer stored"
            ) from error
        raise

    data, width, height = await asyncio.to_thread(render_export, original, recipe)

    key = f"{job_id}.png"
    await asyncio.to_thread(store.put, store.exports, key, data, "image/png")

    return {
        "key": key,
        "contentType": "image/png",
        "width": width,
        "height": height,
        "bytes": len(data),
    }


async def _poll_once(database: DatabaseConfig, store: ObjectStore) -> bool:
    """One turn of the loop. True when something was done, so the caller can
    come straight back rather than sleeping through a queue that has more in it.
    """
    with connection(database) as handle:
        claimed = claim_next(handle)

        if claimed is None:
            return False

        logger.info("export %s started", claimed.id)

        try:
            result = await _run_job(claimed.id, claimed.payload, store)
        except ExportFailed as error:
            logger.warning("export %s failed: %s", claimed.id, error)
            mark_failed(handle, claimed.id, str(error))
        except Exception:
            # The loop survives a job it did not expect to fail. The message the
            # person sees is deliberately not the exception's: that one describes
            # our insides, and it stays in the log where it belongs.
            logger.exception("export %s failed unexpectedly", claimed.id)
            mark_failed(handle, claimed.id, "the export could not be completed")
        else:
            mark_done(handle, claimed.id, result)
            logger.info("export %s done: %s bytes", claimed.id, result["bytes"])

        return True


async def run(database: DatabaseConfig, store: ObjectStore) -> None:
    """Poll until cancelled."""
    with connection(database) as handle:
        reclaimed = reclaim_stale(handle, older_than=STALE_AFTER)

    if reclaimed:
        logger.warning("%d export(s) left running by a previous process, requeued", reclaimed)

    while True:
        try:
            worked = await _poll_once(database, store)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Losing the database is the case this covers: without it the loop
            # would end on the first outage and exports would stop for good,
            # with the service otherwise healthy and saying nothing.
            logger.exception("the export worker could not poll; retrying")
            worked = False

        if not worked:
            await asyncio.sleep(IDLE_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(_: object) -> Any:
    """Start the worker with the application and stop it with the application.

    Configuration is read here rather than per job, and a missing variable stops
    the service from starting. That is the rule the library follows everywhere
    (`.claude/rules/ml_service.md`): a service that starts without knowing where
    its storage is fails later, on the first export, and looks like a network
    fault rather than an unset variable.
    """
    database = DatabaseConfig.from_environment()
    store = ObjectStore(ObjectStorageConfig.from_environment())

    task = asyncio.create_task(run(database, store), name="export-worker")

    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
