"""``POST /derivatives`` end to end (ADR-27).

Nothing is substituted here. The route's whole job is to run the corpus's own
imaging code over an upload, so faking that code would leave the test proving
only that FastAPI can return JSON.
"""

import base64
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from photoassistant.imaging import FIT_SIZE, PROXY_SIZE  # noqa: E402
from service.main import app  # noqa: E402
from service.routes import derivatives as route  # noqa: E402

client = TestClient(app)


def photograph(width: int = 3000, height: int = 2000, mode: str = "RGB") -> bytes:
    """Something with structure, so a resize has visible work to do."""
    gradient = np.linspace(0.1, 0.9, width, dtype=np.float32)
    plane = np.tile(gradient, (height, 1))
    stack = np.dstack([plane, plane * 0.7, plane * 0.4])

    buffer = io.BytesIO()
    Image.fromarray((stack * 255).astype(np.uint8)).convert(mode).save(buffer, format="PNG")
    return buffer.getvalue()


def post(payload: bytes, filename: str = "photo.png"):
    return client.post("/derivatives", files={"image": (filename, payload, "image/png")})


def decode(part: dict) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(part["data"])))


def test_both_derivatives_come_back_at_the_documented_sizes():
    body = post(photograph()).json()

    assert max(body["fit"]["width"], body["fit"]["height"]) == FIT_SIZE
    assert max(body["proxy"]["width"], body["proxy"]["height"]) == PROXY_SIZE
    assert body["source_width"] == 3000
    assert body["source_height"] == 2000


def test_the_formats_are_the_ones_the_corpus_uses():
    """PNG for the measured size, JPEG for the one that is only looked at.

    Swapping them would put compression noise into the image the search compares
    against 25.000 others, which is the mistake the format choice exists to
    prevent.
    """
    body = post(photograph()).json()

    assert body["fit"]["content_type"] == "image/png"
    assert body["proxy"]["content_type"] == "image/jpeg"
    assert decode(body["fit"]).format == "PNG"
    assert decode(body["proxy"]).format == "JPEG"


def test_the_encoded_images_decode_to_the_sizes_they_claim():
    """The response says how big each one is; a caller stores that in the database."""
    body = post(photograph()).json()

    for part in (body["fit"], body["proxy"]):
        assert decode(part).size == (part["width"], part["height"])


def test_a_greyscale_upload_comes_back_as_three_channels():
    """Everything downstream — CLIP, the renderer — expects three channels."""
    body = post(photograph(mode="L")).json()

    assert decode(body["fit"]).convert("RGB").size == (body["fit"]["width"], body["fit"]["height"])


def test_an_upload_smaller_than_the_targets_is_not_enlarged():
    body = post(photograph(width=400, height=300)).json()

    assert (body["fit"]["width"], body["fit"]["height"]) == (400, 300)
    assert (body["proxy"]["width"], body["proxy"]["height"]) == (400, 300)


def test_something_that_is_not_an_image_is_refused_with_400():
    """The API validates type and size without decoding; this is where a lie is caught."""
    response = post(b"this is not a photograph")

    assert response.status_code == 400
    assert "readable image" in response.json()["detail"]


def test_an_empty_upload_is_refused():
    response = post(b"")

    assert response.status_code == 400


def test_an_upload_over_the_ceiling_is_refused_with_413():
    """Its own limit, because a service must not rely on someone else's validation."""
    response = post(b"\x89PNG\r\n\x1a\n" + b"\x00" * (route.MAXIMUM_UPLOAD_BYTES + 1))

    assert response.status_code == 413


def test_the_route_reads_no_storage_and_writes_none():
    """ADR-27 keeps ownership with the API: bytes in, bytes out.

    Checked by the module's imports rather than by watching it run — an object
    store it cannot reach is one it cannot start using by accident.
    """
    source = route.__file__

    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    assert "ObjectStore" not in text
    assert "boto3" not in text


def rotated_portrait() -> bytes:
    """A portrait photograph stored sideways, as a camera held on its side writes it.

    The pixels are 900 wide by 600 tall; EXIF orientation 6 means "rotate a
    quarter turn clockwise to display", so the upright image is 600x900.
    """
    from PIL import Image as PilImage

    image = PilImage.new("RGB", (900, 600), (120, 90, 60))
    exif = PilImage.Exif()
    exif[0x0112] = 6  # Orientation

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_a_sideways_photograph_comes_back_upright():
    """Not cosmetic: pre512 is what CLIP embeds.

    A camera held on its side writes the pixels in sensor order and records the
    quarter turn in a tag. Ignoring it matches a sideways image against an
    upright corpus, which returns worse scenes and reports nothing.
    """
    response = client.post(
        "/derivatives", files={"image": ("portrait.jpg", rotated_portrait(), "image/jpeg")}
    )
    body = response.json()

    # Taller than wide, because the tag said so — the stored pixels were not.
    assert body["source_height"] > body["source_width"]
    assert body["fit"]["height"] > body["fit"]["width"]
    assert body["proxy"]["height"] > body["proxy"]["width"]
