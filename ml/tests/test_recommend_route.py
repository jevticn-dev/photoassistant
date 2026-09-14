"""``POST /recommend`` end to end, with the expensive parts substituted.

The encoder and the database are replaced, and that is the point rather than a
shortcut: what needs proving here is the **route's** behaviour — that it refuses
what it should, resizes the way the corpus was built, and puts a real image in the
response. Whether CLIP embeds well and whether pgvector searches correctly are
proven where those things live.

The one thing not substituted is the renderer: a preview is a rendered recipe, and
a test that faked it would not notice if the endpoint returned a grey rectangle.
"""

import base64
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from photoassistant.recommender import Candidate, Neighbour, Recommendation  # noqa: E402
from photoassistant.schema import EditRecipe  # noqa: E402
from service.main import app  # noqa: E402
from service.routes import recommend as route  # noqa: E402


def png(width: int = 900, height: int = 600) -> bytes:
    """A photograph-shaped image with structure, not a flat field."""
    gradient = np.linspace(0.1, 0.9, width, dtype=np.float32)
    pixels = np.tile(gradient, (height, 1))
    stack = np.dstack([pixels, pixels * 0.7, pixels * 0.4])

    buffer = io.BytesIO()
    Image.fromarray((stack * 255).astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def candidate(identifier: str, reference: str, distance: float, **edit) -> Candidate:
    return Candidate(
        example_id=identifier,
        photo_reference=reference,
        expert="b",
        recipe=EditRecipe.model_validate({"schema": 1, **edit}),
        fingerprint=np.zeros(30),
        after_key=None,
        photo_distance=distance,
        fit_error=1.2,
    )


class FakeRecommender:
    """Stands in for the real one, and records what the route asked of it."""

    last: dict = {}

    def __init__(self, **arguments):
        FakeRecommender.last = {"built": arguments}

    def recommend(self, image, *, exclude, strategy=None):
        FakeRecommender.last["image_shape"] = image.shape
        FakeRecommender.last["exclude"] = exclude
        return Recommendation(
            suggestions=(
                candidate("1", "a0001", 0.10, tone={"exposure": 0.8}),
                candidate("2", "a0002", 0.14, tone={"contrast": 40}),
                candidate("3", "a0003", 0.19, color={"saturation": -30}),
            ),
            neighbours=(Neighbour(reference="a0001", photo_id="x", distance=0.10),),
            pool_size=250,
        )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(route, "Recommender", FakeRecommender)
    # The shared instance, not the class: the route holds one encoder for the life
    # of the process, and monkeypatch puts the real ``None`` back afterwards.
    monkeypatch.setattr(route, "_embedder", object())
    monkeypatch.setattr(route, "PostgresVectorStore", lambda _connection: object())
    monkeypatch.setattr(route, "connect", lambda _config: _NullConnection())
    monkeypatch.setattr(
        route, "DatabaseConfig", type("C", (), {"from_environment": staticmethod(lambda: None)})
    )
    return TestClient(app)


class _NullConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def post(client, payload: bytes, name: str = "photo.png"):
    return client.post("/recommend", files={"image": (name, payload, "image/png")})


# -- what comes back ----------------------------------------------------------


def test_three_suggestions_come_back_with_their_sources(client) -> None:
    body = post(client, png()).json()

    assert len(body["suggestions"]) == 3
    assert [entry["source_reference"] for entry in body["suggestions"]] == [
        "a0001",
        "a0002",
        "a0003",
    ]
    assert body["pool_size"] == 250


def test_each_preview_is_a_real_jpeg_of_the_upload(client) -> None:
    """Not a placeholder: decoded, and the right size for the corpus it came from."""
    body = post(client, png(900, 600)).json()

    for entry in body["suggestions"]:
        with Image.open(io.BytesIO(base64.b64decode(entry["preview"]))) as image:
            assert image.format == "JPEG"
            assert max(image.size) == route.PREVIEW_SIZE
            assert image.size == (512, 341)  # aspect kept, long side at 512


def test_the_previews_differ_because_the_recipes_do(client) -> None:
    """Three identical previews would mean the recipes never reached the renderer."""
    previews = {entry["preview"] for entry in post(client, png()).json()["suggestions"]}

    assert len(previews) == 3


def test_the_recipe_is_a_schema_document_the_editor_can_parse(client) -> None:
    body = post(client, png()).json()

    recipe = body["suggestions"][0]["recipe"]
    assert recipe["schema"] == 1
    assert EditRecipe.model_validate(recipe).tone.exposure == pytest.approx(0.8)


# -- what the route does with the upload --------------------------------------


def test_the_image_reaches_the_recommender_at_the_measured_size(client) -> None:
    """512 on the long side: the resolution the recipes were fitted and judged at."""
    post(client, png(1600, 900))

    assert max(FakeRecommender.last["image_shape"][:2]) == route.PREVIEW_SIZE


def test_a_small_image_is_not_enlarged(client) -> None:
    """Upscaling would invent detail the corpus never had."""
    post(client, png(300, 200))

    assert FakeRecommender.last["image_shape"][:2] == (200, 300)


def test_a_real_request_hides_nothing(client) -> None:
    """The held-out set is an evaluation device; a user's request excludes nobody."""
    post(client, png())

    assert FakeRecommender.last["exclude"] == frozenset()


def test_the_shipped_strategy_is_the_one_the_numbers_chose(client) -> None:
    post(client, png())

    strategy = FakeRecommender.last["built"]["strategy"]
    assert strategy.name == "top-per-scene-bestfit"


# -- refusals -----------------------------------------------------------------


def test_something_that_is_not_an_image_is_refused_with_400(client) -> None:
    response = post(client, b"this is not a PNG", name="lie.png")

    assert response.status_code == 400
    assert "image" in response.json()["detail"]


def test_an_empty_upload_is_refused(client) -> None:
    assert post(client, b"").status_code == 400


def test_an_oversized_upload_is_refused_with_413(client, monkeypatch) -> None:
    """A service does not rely on someone else having validated for it."""
    monkeypatch.setattr(route, "MAXIMUM_UPLOAD_BYTES", 100)

    assert post(client, png()).status_code == 413


def test_a_request_without_a_file_is_rejected_by_validation(client) -> None:
    assert client.post("/recommend").status_code == 422


def test_the_encoder_is_built_once_for_the_process(monkeypatch) -> None:
    """Guards a defect that cost seconds per request without ever failing.

    ``ClipEmbedder`` loads its weights on first use, per instance. Constructing one
    inside the handler is therefore a full model load on every upload — correct
    output, unusable latency, and nothing in a test would have noticed.
    """
    monkeypatch.setattr(route, "_embedder", None)
    built = []

    class CountingEmbedder:
        def __init__(self) -> None:
            built.append(1)

    monkeypatch.setattr(route, "ClipEmbedder", CountingEmbedder)

    assert route.embedder() is route.embedder()
    assert len(built) == 1
