"""The full-resolution export: bands, and the queue the worker takes jobs from."""

from __future__ import annotations

import io
import json
from datetime import timedelta

import numpy as np
import pytest
from PIL import Image

from photoassistant.imaging import encode_png_quantised, render_full_resolution
from photoassistant.renderer import quantise, render
from photoassistant.schema import from_json
from photoassistant.storage import claim_next, mark_done, mark_failed, reclaim_stale

RECIPE = from_json(
    json.dumps(
        {
            "schema": 1,
            "white_balance": {"temperature": 14, "tint": -6},
            "tone": {
                "exposure": 0.35,
                "contrast": 18,
                "highlights": -30,
                "shadows": 24,
                "whites": 10,
                "blacks": -8,
            },
            "color": {"saturation": 8, "vibrance": 12},
            "tone_curve": {"points": [[0, 0], [0.25, 0.2], [0.75, 0.8], [1, 1]]},
        }
    )
)

NEUTRAL = from_json(json.dumps({"schema": 1}))


def _image(height: int, width: int) -> np.ndarray:
    rng = np.random.default_rng(20260921)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def _whole(pixels: np.ndarray, recipe: object) -> np.ndarray:
    return quantise(render(pixels.astype(np.float32) / np.float32(255.0), recipe))


# -- the band render --------------------------------------------------------


@pytest.mark.parametrize("band_rows", [1, 7, 64, 256, 4096])
def test_bands_do_not_change_a_single_pixel(band_rows: int) -> None:
    """The property the whole approach rests on.

    Every operation in the pipeline reads one pixel and writes that pixel — no
    convolution, no neighbourhood, no statistic over the image — so a band has
    everything it needs and the split cannot show. If a step is ever added that
    looks at a neighbour, this is the test that fails, and it fails loudly
    rather than leaving seams somebody notices in an exported photograph.
    """
    pixels = _image(300, 71)

    assert np.array_equal(
        render_full_resolution(pixels, RECIPE, band_rows=band_rows),
        _whole(pixels, RECIPE),
    )


def test_a_band_taller_than_the_image_is_the_whole_image() -> None:
    pixels = _image(40, 40)

    assert np.array_equal(
        render_full_resolution(pixels, RECIPE, band_rows=10_000),
        _whole(pixels, RECIPE),
    )


def test_a_neutral_recipe_returns_the_photograph_unchanged() -> None:
    # Every step is skipped, so what comes back must be what went in — the same
    # identity the renderer's own tests hold it to, through the band path.
    pixels = _image(100, 60)

    assert np.array_equal(render_full_resolution(pixels, NEUTRAL), pixels)


def test_the_height_need_not_divide_by_the_band() -> None:
    # 101 rows in bands of 8 leaves a final band of 5. An off-by-one here would
    # drop or duplicate rows at the bottom of every export.
    pixels = _image(101, 33)
    out = render_full_resolution(pixels, RECIPE, band_rows=8)

    assert out.shape == pixels.shape
    assert np.array_equal(out, _whole(pixels, RECIPE))


@pytest.mark.parametrize("band_rows", [0, -1])
def test_a_band_of_nothing_is_refused(band_rows: int) -> None:
    with pytest.raises(ValueError, match="band_rows"):
        render_full_resolution(_image(10, 10), RECIPE, band_rows=band_rows)


def test_something_that_is_not_an_image_is_refused() -> None:
    with pytest.raises(ValueError, match="image"):
        render_full_resolution(np.zeros((10, 10), dtype=np.uint8), RECIPE)


def test_the_encoded_export_is_lossless() -> None:
    """PNG, so what is downloaded is what was rendered (§B120).

    Decoded back, the file has to be the exact array — not close to it. The
    measurement that chose PNG over JPEG rests on this being true of one side
    and false of the other.
    """
    pixels = _image(64, 48)
    rendered = render_full_resolution(pixels, RECIPE)
    encoded = encode_png_quantised(rendered)

    assert encoded.content_type == "image/png"
    assert (encoded.height, encoded.width) == (64, 48)

    with Image.open(io.BytesIO(encoded.data)) as handle:
        assert np.array_equal(np.asarray(handle.convert("RGB"), dtype=np.uint8), rendered)


# -- the queue --------------------------------------------------------------


class _Cursor:
    """A cursor that records statements and answers with what a test set up."""

    def __init__(self, owner: _Connection) -> None:
        self._owner = owner

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, parameters: tuple) -> None:
        self._owner.statements.append((" ".join(statement.split()), parameters))
        self.rowcount = self._owner.rowcount

    def fetchone(self) -> tuple | None:
        return self._owner.rows.pop(0) if self._owner.rows else None


class _Connection:
    def __init__(self, rows: list | None = None, rowcount: int = 0) -> None:
        self.rows = rows or []
        self.rowcount = rowcount
        self.statements: list[tuple[str, tuple]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)


def test_claiming_a_job_takes_it_in_one_statement() -> None:
    """Two statements would be a race: a second worker can select the same row
    between the select and the update. The lock and the skip are what make two
    workers take two jobs rather than both taking the first.
    """
    connection = _Connection(rows=[("0199-id", {"originalKey": "k", "recipe": {"schema": 1}})])
    claimed = claim_next(connection)

    assert claimed is not None
    assert claimed.id == "0199-id"
    assert claimed.payload["originalKey"] == "k"

    statement, parameters = connection.statements[0]
    assert statement.count("update jobs") == 1
    assert "for update skip locked" in statement
    assert "order by created_at" in statement
    assert parameters == ("Running", "Pending", "Export")


def test_an_empty_queue_claims_nothing() -> None:
    assert claim_next(_Connection()) is None


def test_a_payload_that_is_not_an_object_is_a_defect_rather_than_a_failed_job() -> None:
    # The column is jsonb and the API writes an object into it. A string here
    # would mean the schema changed under us, which is worth stopping for.
    with pytest.raises(TypeError, match="payload"):
        claim_next(_Connection(rows=[("0199-id", "not an object")]))


def test_finishing_a_job_records_the_result_and_clears_the_error() -> None:
    connection = _Connection()
    mark_done(connection, "0199-id", {"key": "0199-id.png", "bytes": 12})

    statement, parameters = connection.statements[0]
    assert "error = null" in statement
    assert parameters[0] == "Done"
    assert json.loads(parameters[1])["key"] == "0199-id.png"


def test_a_failure_message_is_stored_but_bounded() -> None:
    connection = _Connection()
    mark_failed(connection, "0199-id", "x" * 5000)

    _, parameters = connection.statements[0]
    assert parameters[0] == "Failed"
    assert len(parameters[1]) == 2000


def test_startup_requeues_what_a_killed_process_left_running() -> None:
    """Without this a job stays Running for good and the person waits for
    something that died — the failure phase 2 proved against by killing
    processes on purpose.
    """
    connection = _Connection(rowcount=2)
    reclaimed = reclaim_stale(connection, older_than=timedelta(minutes=15))

    assert reclaimed == 2

    statement, parameters = connection.statements[0]
    assert "updated_at < now() -" in statement
    assert parameters[:3] == ("Pending", "Running", "Export")
