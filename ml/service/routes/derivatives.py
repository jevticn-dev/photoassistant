"""``POST /derivatives`` — an uploaded photograph in, its two stored sizes out.

**Why this lives here and not in the .NET API** (ADR-27). The 512px derivative is
not merely a small copy: it is the input to a comparison against 25.000 images,
and those were produced by ``photoassistant.imaging``. That code averages in
linear light, hits an exact target size, keeps JPEG chroma at full resolution and
stores the 512 as PNG — four choices no general-purpose imaging library makes by
default. Resize an upload any other way and it stops being the same kind of image
as the corpus it is matched against. Nothing fails; the search quietly returns
slightly different neighbours.

**The service still owns nothing.** It reads no storage and writes none: bytes in,
bytes out. The .NET API keeps the original, writes both derivatives to MinIO and
owns the rows, exactly as plan §9 assigns it. That is why the response carries the
images rather than object keys.

**This service does not know about users** — no authentication, no ownership. The
.NET API is the only public door (`.claude/rules/ml_service.md`); this endpoint
answers whoever reaches it on the private network, which is by design nobody but
that API.
"""

import base64
import io
from typing import Annotated

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from photoassistant.imaging import Derivative, derive_from_srgb

router = APIRouter(tags=["derivatives"])

# The same ceiling the recommend route uses. Generous enough for a photograph
# from a phone or a camera, small enough that a mistake cannot fill memory. The
# .NET side has its own limit; this one exists because a service must not depend
# on someone else's validation.
MAXIMUM_UPLOAD_BYTES = 40 * 1024 * 1024


class EncodedImage(BaseModel):
    """One derivative, ready for the caller to store."""

    data: str = Field(description="The encoded image, base64")
    content_type: str = Field(description="image/png for the fit, image/jpeg for the proxy")
    width: int
    height: int


class DerivativesResponse(BaseModel):
    fit: EncodedImage = Field(description="512px PNG — what search and fitting run on")
    proxy: EncodedImage = Field(description="2048px JPEG — what the editor renders from")
    source_width: int = Field(description="Width of the upload as decoded")
    source_height: int = Field(description="Height of the upload as decoded")


def _encode(derivative: Derivative) -> EncodedImage:
    return EncodedImage(
        data=base64.b64encode(derivative.data).decode("ascii"),
        content_type=derivative.content_type,
        width=derivative.width,
        height=derivative.height,
    )


def _decode(payload: bytes) -> np.ndarray:
    """Bytes to an 8-bit sRGB array, refusing anything that is not an image.

    ``convert("RGB")`` is doing more than it looks: it drops an alpha channel and
    turns a greyscale or palette image into three channels, so everything
    downstream sees one shape. A PNG with transparency composites onto black,
    which is what the editor would show anyway.
    """
    try:
        with Image.open(io.BytesIO(payload)) as handle:
            handle.load()
            return np.asarray(handle.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="not a readable image") from error


@router.post(
    "/derivatives",
    response_model=DerivativesResponse,
    summary="The 512px and 2048px derivatives of an uploaded photograph",
)
async def derivatives(
    image: Annotated[UploadFile, File(description="The photograph to derive from")],
) -> DerivativesResponse:
    payload = await image.read()

    if not payload:
        raise HTTPException(status_code=400, detail="the upload is empty")
    if len(payload) > MAXIMUM_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"the upload exceeds {MAXIMUM_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    pixels = _decode(payload)
    source_height, source_width = pixels.shape[:2]

    result = derive_from_srgb(pixels)
    # `derive_from_srgb` always makes both; the optional type comes from the
    # corpus path, where expert results get no proxy.
    assert result.proxy is not None

    return DerivativesResponse(
        fit=_encode(result.fit),
        proxy=_encode(result.proxy),
        source_width=source_width,
        source_height=source_height,
    )
