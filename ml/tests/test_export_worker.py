"""The worker that turns an export job into a stored file.

What is exercised here is the job path — what it refuses, what it stores, and
what it says when it cannot. The render itself is covered by ``test_export.py``
and by the golden test; nothing is repeated.
"""

import asyncio
import io
import json

import numpy as np
import pytest
from botocore.exceptions import ClientError
from PIL import Image

from service.worker import ExportFailed, _run_job, render_export

RECIPE = {
    "schema": 1,
    "white_balance": {"temperature": 10, "tint": 0},
    "tone": {
        "exposure": 0.2,
        "contrast": 0,
        "highlights": 0,
        "shadows": 0,
        "whites": 0,
        "blacks": 0,
    },
    "color": {"saturation": 0, "vibrance": 0},
    "tone_curve": {"points": [[0, 0], [1, 1]]},
}


def _png(width: int = 32, height: int = 24, *, rotate: int | None = None) -> bytes:
    rng = np.random.default_rng(20260921)
    pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    image = Image.fromarray(pixels, mode="RGB")

    if rotate is not None:
        exif = image.getexif()
        exif[274] = rotate  # Orientation
        image.save(buffer, format="JPEG", exif=exif, quality=95, subsampling=0)
    else:
        image.save(buffer, format="PNG")

    return buffer.getvalue()


class _Store:
    """Object storage as the worker uses it: one read, one write."""

    originals = "originals"
    exports = "exports"

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.written: dict[str, tuple[bytes, str]] = {}

    def get(self, bucket: str, key: str) -> bytes:
        if key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "GetObject",
            )
        return self.objects[key]

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.written[key] = (data, content_type)


def run(payload: dict, store: _Store, job_id: str = "0199-job") -> dict:
    return asyncio.run(_run_job(job_id, payload, store))


def test_a_finished_export_is_a_png_named_after_its_job() -> None:
    store = _Store({"originals/a.png": _png()})
    result = run({"originalKey": "originals/a.png", "recipe": RECIPE}, store)

    assert result == {
        "key": "0199-job.png",
        "contentType": "image/png",
        "width": 32,
        "height": 24,
        "bytes": len(store.written["0199-job.png"][0]),
    }
    assert store.written["0199-job.png"][1] == "image/png"


def test_the_export_is_the_full_resolution_of_the_original() -> None:
    # Not the proxy: the point of the job is the size the editor never loaded.
    store = _Store({"originals/big.png": _png(width=600, height=400)})
    result = run({"originalKey": "originals/big.png", "recipe": RECIPE}, store)

    assert (result["width"], result["height"]) == (600, 400)


def test_a_sideways_original_is_exported_upright() -> None:
    """The proxy the editor showed was made upright, so the export has to be.

    Orientation 6 means "turn a quarter turn": the stored pixels are 32x24 and
    what the person saw — and what must come back — is 24x32.
    """
    store = _Store({"originals/rotated.jpg": _png(rotate=6)})
    result = run({"originalKey": "originals/rotated.jpg", "recipe": RECIPE}, store)

    assert (result["width"], result["height"]) == (24, 32)


def test_a_job_without_an_original_says_so_rather_than_raising() -> None:
    with pytest.raises(ExportFailed, match="names no original"):
        run({"recipe": RECIPE}, _Store())


def test_a_job_without_a_recipe_says_so() -> None:
    with pytest.raises(ExportFailed, match="no recipe"):
        run({"originalKey": "originals/a.png"}, _Store({"originals/a.png": _png()}))


def test_a_recipe_the_schema_refuses_is_a_failed_job_not_a_crash() -> None:
    # Validated here although the API validated it too: a service does not
    # depend on someone else's validation.
    store = _Store({"originals/a.png": _png()})

    with pytest.raises(ExportFailed, match="schema refuses"):
        run({"originalKey": "originals/a.png", "recipe": {"nonsense": True}}, store)


def test_a_recipe_without_a_schema_version_is_refused() -> None:
    # A stored document has to declare its version — the rule `from_json`
    # enforces and `model_validate` would quietly default.
    store = _Store({"originals/a.png": _png()})
    without = {key: value for key, value in RECIPE.items() if key != "schema"}

    with pytest.raises(ExportFailed, match="schema refuses"):
        run({"originalKey": "originals/a.png", "recipe": without}, store)


def test_an_original_that_is_gone_is_a_message_rather_than_an_exception() -> None:
    # Reachable: the project could be deleted while its export is queued.
    with pytest.raises(ExportFailed, match="no longer stored"):
        run({"originalKey": "originals/missing.png", "recipe": RECIPE}, _Store())


def test_something_stored_that_is_not_an_image_is_a_message_too() -> None:
    store = _Store({"originals/a.png": b"this is not a photograph"})

    with pytest.raises(ExportFailed, match="could not be read as an image"):
        run({"originalKey": "originals/a.png", "recipe": RECIPE}, store)


def test_the_rendered_file_matches_the_library_render() -> None:
    """The worker adds decoding and encoding around the renderer and nothing
    else. Anything it did to the pixels of its own would show here.
    """
    from photoassistant.imaging import render_full_resolution
    from photoassistant.schema import from_json

    original = _png()
    data, width, height = render_export(original, from_json(json.dumps(RECIPE)))

    with Image.open(io.BytesIO(original)) as handle:
        pixels = np.asarray(handle.convert("RGB"), dtype=np.uint8)
    with Image.open(io.BytesIO(data)) as handle:
        exported = np.asarray(handle.convert("RGB"), dtype=np.uint8)

    assert (width, height) == (32, 24)
    assert np.array_equal(
        exported, render_full_resolution(pixels, from_json(json.dumps(RECIPE)))
    )
