"""The local cache of derivatives, and the summary arithmetic that reads it.

No MinIO: the store is replaced by a counter, which is the point — the claim worth
pinning is that the **second** read does not cross the network, and a test against
the real store could not tell the difference.
"""

import json

import numpy as np
import pytest
from PIL import Image

from pipeline import derivative_cache
from pipeline.measure_expert_agreement import distribution


class FakeStore:
    """Hands back one PNG and records what was asked of it."""

    derivatives = "derivatives"

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.requested: list[tuple[str, str]] = []

    @property
    def reads(self) -> int:
        return len(self.requested)

    def get(self, bucket: str, key: str) -> bytes:
        self.requested.append((bucket, key))
        return self.payload


@pytest.fixture
def png(tmp_path) -> bytes:
    path = tmp_path / "source.png"
    Image.fromarray(np.full((4, 4, 3), 128, dtype=np.uint8)).save(path)
    return path.read_bytes()


@pytest.fixture
def cache(tmp_path, png, monkeypatch):
    store = FakeStore(png)
    monkeypatch.setenv("EVAL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(derivative_cache, "store", lambda: store)
    return store


def test_the_first_read_downloads_and_the_second_does_not(cache) -> None:
    """Fifteen ablation arms over the same 3.000 objects is why this exists."""
    derivative_cache.fetch("fivek/a0001/pre512.png")
    derivative_cache.fetch("fivek/a0001/pre512.png")

    assert cache.reads == 1


def test_it_reads_the_derivatives_bucket_and_asks_for_the_key_given(cache) -> None:
    """Originals are user uploads and exports are rendered output; neither is this."""
    derivative_cache.fetch("fivek/a0001/pre512.png")

    assert cache.requested == [("derivatives", "fivek/a0001/pre512.png")]


@pytest.mark.usefixtures("cache")
def test_the_local_path_mirrors_the_object_key() -> None:
    path = derivative_cache.fetch("fivek/a0001-jmac/after512-b.png")

    assert path.parts[-3:] == ("fivek", "a0001-jmac", "after512-b.png")
    assert path.is_file()


@pytest.mark.usefixtures("cache")
def test_no_partial_file_is_left_behind() -> None:
    """A truncated PNG would be reused happily by every later run (§B18)."""
    path = derivative_cache.fetch("fivek/a0001/pre512.png")

    assert not list(path.parent.glob("*.part"))


@pytest.mark.usefixtures("cache")
def test_an_image_comes_back_as_srgb_floats() -> None:
    image = derivative_cache.image("fivek/a0001/pre512.png")

    assert image.shape == (4, 4, 3)
    assert image.dtype == np.float64
    assert image.max() <= 1.0
    assert image[0, 0, 0] == pytest.approx(128 / 255)


@pytest.mark.usefixtures("cache")
def test_a_cached_file_survives_a_new_process(tmp_path) -> None:
    """The cache is a directory, not an object — that is what makes it shareable."""
    derivative_cache.fetch("fivek/a0001/pre512.png")

    assert (tmp_path / "cache" / "fivek" / "a0001" / "pre512.png").is_file()


# -- the summary arithmetic ---------------------------------------------------


def test_a_distribution_reports_the_shape_not_just_the_middle() -> None:
    summary = distribution([float(value) for value in range(1, 101)])

    assert summary["count"] == 100
    assert summary["min"] == pytest.approx(1.0)
    assert summary["median"] == pytest.approx(50.5)
    assert summary["max"] == pytest.approx(100.0)
    assert summary["p10"] < summary["median"] < summary["p90"]


def test_undefined_values_are_dropped_rather_than_counted_as_zero() -> None:
    """A photograph with one usable edit has no pairs, and no disagreement to report."""
    summary = distribution([1.0, None, 3.0])

    assert summary["count"] == 2
    assert summary["mean"] == pytest.approx(2.0)


def test_nothing_measurable_reports_nothing() -> None:
    assert distribution([None, None]) == {}


def test_the_artefact_is_json_a_person_can_read() -> None:
    """It carries the per-photograph thresholds the harness looks up, so it is inspected."""
    summary = distribution([1.0, 2.0, 3.0])

    assert json.loads(json.dumps(summary)) == summary
