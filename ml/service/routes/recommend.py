"""``POST /recommend`` — a photograph in, three edit recipes out.

The route is thin on purpose: it validates the upload, calls the library, and maps
the result. Every decision it embodies was measured in phase 3 and is recorded in
``docs/phases/phase-3.md``; nothing here chooses anything.

**The configuration it ships is the one the numbers picked** (decision L): one edit
from each of the three nearest scenes, preferring the edit schema v1 reproduced most
faithfully. No fingerprint, no clustering, no second model — those exist behind the
interfaces and lost, measurably, which is itself the finding.

**The response carries recipes and nothing else** (phase 4, decision C). It used to
render a 512px preview of each, which measured 157 ms of a 239 ms request and 141 KB
of its body (§B84) — more than half the time, for an image the browser can produce
itself. The frontend runs the same renderer, proven to agree with this one by the
golden test, over the 2048px proxy it loads for the editor anyway. So the person
chooses from the very image they are about to edit, rather than from a smaller one
rendered elsewhere.

**This service does not know about users.** No authentication, no ownership, no
identifiers of people. The .NET API is the only public door and owns all of that
(`.claude/rules/ml_service.md`); this endpoint answers whoever can reach it on the
private network, which is by design nobody but that API.
"""

import io
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from photoassistant.imaging import FIT_SIZE, fit_size_for, resample_area
from photoassistant.recommender import (
    ClipEmbedder,
    PostgresVectorStore,
    Recommender,
    TopCandidates,
)
from photoassistant.renderer import srgb_decode, srgb_encode
from photoassistant.storage import DatabaseConfig, connect

router = APIRouter(tags=["recommend"])

# The resolution everything downstream was measured at: recipes were fitted against
# 512px results and the evaluation searched at 512, so an image embedded at
# another size would not be the thing that was measured. FIT_SIZE is that same
# constant, taken from the phase 2 derivatives rather than repeated here.
SEARCH_SIZE = FIT_SIZE

# Generous enough for a phone photograph, small enough that a mistake cannot fill
# memory. The .NET side will have its own limit; this one exists because a service
# must not depend on someone else's validation.
MAXIMUM_UPLOAD_BYTES = 40 * 1024 * 1024

# The encoder is built once for the life of the process, not once per request.
# ``ClipEmbedder`` loads its weights lazily **per instance**, so constructing one
# inside the handler would fetch a gigabyte of parameters on every upload — the
# kind of defect that does not fail, it just makes the endpoint unusable. Holding
# it here costs the memory of one model and is measured by
# `pipeline/measure_latency.py`, whose warm-up exists precisely to pay this once.
_embedder: ClipEmbedder | None = None


def embedder() -> ClipEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = ClipEmbedder()
    return _embedder


class Suggestion(BaseModel):
    """One proposal: what to apply, where it came from, and what it looks like."""

    recipe: dict[str, Any] = Field(description="The edit in schema v1, ready to apply")
    source_reference: str = Field(description="Photograph the edit was taken from")
    expert: str | None = Field(description="Which FiveK expert produced it, a to e")
    scene_distance: float = Field(description="Cosine distance from the upload to that scene")


class RecommendResponse(BaseModel):
    suggestions: list[Suggestion]
    pool_size: int = Field(description="Candidate edits considered before choosing")
    neighbours: int = Field(description="Similar photographs the search returned")


def _decode(payload: bytes) -> np.ndarray:
    """Bytes to an sRGB array, refusing anything that is not an image.

    Pillow is asked to verify before decoding: a file that merely claims to be a
    PNG should fail here with a 400 rather than deep inside the renderer.
    """
    try:
        with Image.open(io.BytesIO(payload)) as handle:
            handle.load()
            pixels = np.asarray(handle.convert("RGB"), dtype=np.float64)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(status_code=400, detail="not a readable image") from error

    return pixels / 255.0


@router.post(
    "/recommend",
    response_model=RecommendResponse,
    summary="Three edit suggestions for an uploaded photograph",
)
def recommend(
    image: Annotated[UploadFile, File(description="The photograph to suggest edits for")],
) -> RecommendResponse:
    # Deliberately **not** ``async``. Everything this handler does — decoding,
    # encoding through CLIP, searching — is blocking work in C and NumPy,
    # several hundred milliseconds of it. In an async handler that time is
    # spent on the event loop, where it stalls every other connection including the
    # health check; declared like this, FastAPI runs it in the threadpool, which is
    # where blocking work belongs. The database connection is opened per request
    # rather than shared, because a psycopg connection is not safe across threads.
    payload = image.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(payload) > MAXIMUM_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="image too large")

    # One size for everything that follows. The encoder resizes internally anyway;
    # what matters is that the image is embedded at the resolution the corpus
    # vectors were computed at.
    #
    # Down to size **in linear light**, the way the pipeline made every derivative
    # this corpus was built from (§A10). Averaging gamma-encoded values darkens the
    # result, because the average of two encoded values is not the encoding of
    # their average — so the upload is decoded, averaged, and encoded back rather
    # than resized where it stands. An image subtly darker than the corpus it is
    # compared against is a defect nobody could name.
    decoded = _decode(payload)
    height, width = decoded.shape[:2]
    small = srgb_encode(
        resample_area(srgb_decode(decoded), fit_size_for(height, width, SEARCH_SIZE))
    )

    with connect(DatabaseConfig.from_environment()) as connection:
        recommender = Recommender(
            embedder=embedder(),
            store=PostgresVectorStore(connection),
            strategy=TopCandidates(one_per_photograph=True, prefer_best_fit=True),
        )
        # Nothing is hidden from a real request. The argument is written out rather
        # than defaulted, because an evaluation that forgets it measures nothing and
        # the signature refuses to let that happen quietly (decision A).
        result = recommender.recommend(small, exclude=frozenset())

    return RecommendResponse(
        suggestions=[
            Suggestion(
                recipe=candidate.recipe.to_dict(),
                source_reference=candidate.photo_reference,
                expert=candidate.expert,
                scene_distance=candidate.photo_distance,
            )
            for candidate in result.suggestions
        ],
        pool_size=result.pool_size,
        neighbours=len(result.neighbours),
    )
