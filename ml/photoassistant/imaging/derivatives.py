"""The two stored sizes, made from one full-resolution rendition (ADR-3b).

512px
    What fitting and fingerprints run on. A recipe is independent of resolution,
    so nothing is lost by fitting small, and everything is gained in time.

2048px
    What the editor renders its live preview from. Display only.

**The formats are not interchangeable, and the reason is measurement.** The 512px
image is the *target of the fit*: the residual we report is the difference between
our render and that file. Store it as JPEG and the compression noise becomes part
of the residual, indistinguishable from the model failing. It is PNG, lossless.
The 2048px proxy is only ever looked at, so it is JPEG.

That is the same rule ADR-17 applies to gamut clipping and phase 1 applied to
Pillow's silent 16-bit truncation: **anything standing between the source and the
error measurement is either lossless, or measured and reported separately.**
"""

import io
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFile

from photoassistant.imaging.prophoto import prophoto_to_srgb
from photoassistant.imaging.resample import resample_area
from photoassistant.renderer.color import srgb_decode, srgb_encode
from photoassistant.renderer.pipeline import quantise

FIT_SIZE = 512
PROXY_SIZE = 2048

# Chosen in plan §5.1 (3b). High enough that the proxy is not what the user
# notices, low enough that 5000 of them are a few gigabytes.
PROXY_JPEG_QUALITY = 85


@dataclass(frozen=True)
class Derivative:
    """One encoded image, ready to be written to object storage."""

    data: bytes
    content_type: str
    height: int
    width: int


@dataclass(frozen=True)
class Derivatives:
    """What one rendition yields, plus the number ADR-17 insists on.

    ``gamut_fraction`` is the share of pixels where at least one channel left
    [0, 1] on the way out of ProPhoto. It is carried alongside the images rather
    than logged and forgotten, because the fitting residual is only interpretable
    next to it: a photograph with saturated colour outside sRGB has an error floor
    that has nothing to do with our model.
    """

    fit: Derivative
    proxy: Derivative | None
    gamut_fraction: float


def fit_size_for(height: int, width: int, longest: int) -> tuple[int, int]:
    """Target size that puts ``longest`` on the longer side, keeping the aspect.

    Never returns a zero dimension. A panorama scaled to 512 on the long side can
    round its short side below one pixel, and an array with a zero axis fails much
    later, somewhere that does not mention the panorama.
    """
    if height <= 0 or width <= 0:
        raise ValueError(f"image has no area: {height}x{width}")

    scale = longest / max(height, width)
    # Not enlarged: a rendition smaller than the target stays as it is. Upscaling
    # would invent detail and make the fit chase pixels nothing measured.
    if scale >= 1.0:
        return height, width
    return max(1, round(height * scale)), max(1, round(width * scale))


def encode_png(srgb: NDArray[np.floating]) -> Derivative:
    """8-bit PNG from an sRGB float image. Lossless, because this one is measured."""
    pixels = quantise(srgb)
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG", optimize=True)
    return Derivative(
        data=buffer.getvalue(),
        content_type="image/png",
        height=pixels.shape[0],
        width=pixels.shape[1],
    )


def encode_jpeg(srgb: NDArray[np.floating], quality: int = PROXY_JPEG_QUALITY) -> Derivative:
    """8-bit JPEG from an sRGB float image. For images that are only displayed."""
    pixels = quantise(srgb)
    buffer = io.BytesIO()

    # `optimize` makes Pillow build the whole scan in one buffer, sized by the
    # module-level MAXBLOCK (64 KiB). An image that compresses badly overflows it
    # and the save fails with "broken data stream" — not a corrupt file, a buffer
    # too small. The corpus never hit it because a photograph compresses; a
    # high-ISO night shot is close enough to noise that it can, and uploads are
    # whatever a user sends. Three bytes a pixel is the worst case that cannot be
    # exceeded, so this makes the failure unreachable rather than unlikely.
    previous = ImageFile.MAXBLOCK
    ImageFile.MAXBLOCK = max(previous, pixels.shape[0] * pixels.shape[1] * 3)
    try:
        Image.fromarray(pixels, mode="RGB").save(
            buffer,
            format="JPEG",
            quality=quality,
            # Chroma kept at full resolution. The default halves it, which is
            # invisible on a photograph and very visible on the saturated edges
            # this dataset is full of — and the proxy is what the editor shows
            # while the user judges colour.
            subsampling=0,
            optimize=True,
        )
    finally:
        ImageFile.MAXBLOCK = previous
    return Derivative(
        data=buffer.getvalue(),
        content_type="image/jpeg",
        height=pixels.shape[0],
        width=pixels.shape[1],
    )


def make_derivatives(rendition: NDArray[np.integer], *, with_proxy: bool) -> Derivatives:
    """Turn one 16-bit ProPhoto rendition into what gets stored.

    ``with_proxy`` is true for the "before" image and false for the five expert
    results: the editor previews a photograph, not an edit of it, so a 2048px copy
    of each expert's version would be five times the storage for something nothing
    reads.

    The conversion happens **once** and both sizes are averaged down from the same
    linear array. Converting twice would be the same arithmetic done twice, and
    converting after downscaling would average ProPhoto values through an sRGB
    matrix — wrong in a way that looks like a mild colour shift.
    """
    linear, gamut_fraction = prophoto_to_srgb(rendition)
    height, width = linear.shape[:2]

    fit_linear = resample_area(linear, fit_size_for(height, width, FIT_SIZE))
    fit = encode_png(srgb_encode(fit_linear))

    proxy = None
    if with_proxy:
        proxy_linear = resample_area(linear, fit_size_for(height, width, PROXY_SIZE))
        proxy = encode_jpeg(srgb_encode(proxy_linear))

    return Derivatives(fit=fit, proxy=proxy, gamut_fraction=gamut_fraction)


def derive_from_srgb(image: NDArray[np.integer]) -> Derivatives:
    """The same two sizes, for a photograph a user uploaded (ADR-27).

    Only the first step differs from :func:`make_derivatives`. A FiveK rendition
    arrives as 16-bit ProPhoto and needs converting; an upload is already sRGB,
    so it only needs decoding to linear light. Everything after that — the area
    average, the sizes, PNG for the fit and JPEG q85 with full chroma for the
    proxy — is shared code, which is the entire point of the decision.

    **Why this function exists at all, rather than resizing in the API.** The
    512px derivative is not just a small copy: it is the input to a comparison
    against 25.000 images produced by the lines below. Resample in gamma space,
    or let JPEG halve the chroma, and the upload is no longer the same kind of
    image as the corpus it is matched against. Nothing fails; the search simply
    returns slightly different neighbours, which is a defect nobody reports
    (ADR-27, notes phase-4 §B99).

    ``gamut_fraction`` is zero by construction. An sRGB file cannot hold a colour
    outside sRGB, so there is nothing to clip and nothing to report — the field
    stays in the shape for callers, rather than becoming an optional that every
    one of them has to test.
    """
    linear = srgb_decode(np.asarray(image, dtype=np.float64) / 255.0)
    height, width = linear.shape[:2]

    fit = encode_png(srgb_encode(resample_area(linear, fit_size_for(height, width, FIT_SIZE))))
    proxy = encode_jpeg(
        srgb_encode(resample_area(linear, fit_size_for(height, width, PROXY_SIZE)))
    )

    return Derivatives(fit=fit, proxy=proxy, gamut_fraction=0.0)
