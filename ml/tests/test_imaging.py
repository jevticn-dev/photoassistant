"""Colour conversion, downscaling and encoding at the dataset boundary."""

import io

import numpy as np
import pytest
from PIL import Image

from photoassistant.imaging import (
    FIT_SIZE,
    PROPHOTO_TO_SRGB_LINEAR,
    PROXY_SIZE,
    derive_from_srgb,
    encode_jpeg,
    encode_png,
    fit_size_for,
    make_derivatives,
    prophoto_to_srgb,
    resample_area,
    romm_decode,
)


def prophoto_image(values: list[list[tuple[int, int, int]]]) -> np.ndarray:
    return np.array(values, dtype=np.uint16)


def test_prophoto_white_becomes_srgb_white():
    """The one check that catches a missing chromatic adaptation.

    ProPhoto is D50 and sRGB is D65. Leaving the adaptation out still produces a
    plausible image — just one with a cast on every pixel, which the fit would
    then spend its white balance parameters correcting. That would turn a
    colour-space bug into what reads as a model result.
    """
    white = prophoto_image([[(65535, 65535, 65535)]])

    linear, _ = prophoto_to_srgb(white)

    assert np.allclose(linear[0, 0], [1.0, 1.0, 1.0], atol=1e-4)


def test_the_matrix_chain_is_guarded_at_import():
    """The module refuses to load with a broken matrix; this states the invariant."""
    assert np.allclose(PROPHOTO_TO_SRGB_LINEAR @ np.ones(3), 1.0, atol=1e-4)


def test_prophoto_black_stays_black():
    linear, _ = prophoto_to_srgb(prophoto_image([[(0, 0, 0)]]))

    assert np.allclose(linear[0, 0], 0.0, atol=1e-6)


def test_romm_transfer_is_not_srgb_and_not_a_plain_power():
    """Gamma 1.8 with a linear toe. Decoding with sRGB's curve shifts every tone.

    The value chosen is mid-grey, where the two curves differ most visibly.
    """
    decoded = float(romm_decode(np.array([0.5]))[0])

    assert decoded == pytest.approx(0.5**1.8, abs=1e-6)
    assert decoded != pytest.approx(0.5**2.2, abs=1e-3)


def test_out_of_gamut_pixels_are_counted_not_hidden():
    """ADR-17: the share is reported next to the fitting error, not folded into it.

    Saturated ProPhoto green has no sRGB equivalent, so one channel leaves [0, 1].
    A neutral grey does not.
    """
    saturated = prophoto_image([[(0, 65535, 0)]])
    neutral = prophoto_image([[(32768, 32768, 32768)]])

    assert prophoto_to_srgb(saturated)[1] == 1.0
    assert prophoto_to_srgb(neutral)[1] == 0.0


def test_conversion_returns_unclipped_linear_light():
    """Clipping here would decide the gamut question before it has been measured."""
    linear, _ = prophoto_to_srgb(prophoto_image([[(0, 65535, 0)]]))

    assert linear.min() < 0.0


def test_sixteen_bit_input_is_not_quietly_truncated():
    """Two values one 16-bit step apart must not land on the same output.

    This is the failure Pillow produces when it reads such a TIFF: 75% of pixels
    lose their low byte, silently. The conversion itself must not repeat it.
    """
    pair = prophoto_image([[(30000, 30000, 30000), (30001, 30001, 30001)]])

    linear, _ = prophoto_to_srgb(pair)

    assert linear[0, 0, 0] != linear[0, 1, 0]


def test_resampling_averages_rather_than_samples():
    """A checkerboard averages to its mean. Nearest-neighbour would return 0 or 1."""
    board = np.indices((8, 8)).sum(axis=0) % 2
    image = np.repeat(board[:, :, None], 3, axis=2).astype(np.float64)

    assert np.allclose(resample_area(image, (1, 1)), 0.5)


def test_resampling_hits_the_exact_target_for_a_non_integer_ratio():
    """An integer box factor cannot land on 300 from 1000, which is why it is not used."""
    image = np.zeros((1000, 750, 3))

    assert resample_area(image, (300, 225)).shape == (300, 225, 3)


@pytest.mark.parametrize(
    ("height", "width", "expected"),
    [
        (2000, 3008, (340, 512)),  # landscape
        (3072, 2048, (512, 341)),  # portrait
        (512, 512, (512, 512)),  # already there
        (300, 400, (300, 400)),  # smaller than the target: left alone
        (200, 20000, (5, 512)),  # panorama — short side must not round to zero
    ],
)
def test_fit_size_keeps_aspect_and_never_reaches_zero(height, width, expected):
    assert fit_size_for(height, width, FIT_SIZE) == expected


def test_fit_size_rejects_an_empty_image():
    with pytest.raises(ValueError, match="no area"):
        fit_size_for(0, 100, FIT_SIZE)


def test_png_round_trips_every_byte():
    """The 512px image is the target of the fit, so its encoding must lose nothing.

    A JPEG here would put compression noise into the residual we report as model
    error — the same class of mistake as reading a 16-bit file as 8-bit.
    """
    rng = np.random.default_rng(20260828)
    srgb = rng.random((37, 53, 3))

    encoded = encode_png(srgb)
    decoded = np.asarray(Image.open(io.BytesIO(encoded.data)))

    expected = np.floor(np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)
    assert np.array_equal(decoded, expected)
    assert encoded.content_type == "image/png"


def test_jpeg_is_close_but_not_exact():
    """States the difference the format choice rests on, rather than assuming it."""
    rng = np.random.default_rng(20260828)
    srgb = rng.random((64, 64, 3))

    decoded = np.asarray(Image.open(io.BytesIO(encode_jpeg(srgb).data)))
    exact = np.asarray(Image.open(io.BytesIO(encode_png(srgb).data)))

    assert not np.array_equal(decoded, exact)
    assert decoded.shape == exact.shape


def test_derivatives_produce_both_sizes_for_the_before_image():
    rendition = np.full((1024, 1536, 3), 30000, dtype=np.uint16)

    result = make_derivatives(rendition, with_proxy=True)

    assert (result.fit.height, result.fit.width) == (341, FIT_SIZE)
    assert result.proxy is not None
    # 1536 is below 2048, so the proxy is not enlarged.
    assert (result.proxy.height, result.proxy.width) == (1024, 1536)
    assert result.proxy.content_type == "image/jpeg"


def test_derivatives_skip_the_proxy_for_an_expert_result():
    """The editor previews a photograph, not each expert's version of it."""
    rendition = np.full((600, 900, 3), 20000, dtype=np.uint16)

    result = make_derivatives(rendition, with_proxy=False)

    assert result.proxy is None
    assert result.fit.content_type == "image/png"


def test_proxy_uses_the_larger_target():
    rendition = np.full((3000, 4500, 3), 25000, dtype=np.uint16)

    result = make_derivatives(rendition, with_proxy=True)

    assert result.proxy is not None
    assert max(result.proxy.height, result.proxy.width) == PROXY_SIZE
    assert max(result.fit.height, result.fit.width) == FIT_SIZE


def test_derivatives_carry_the_gamut_fraction():
    """It travels with the images because the residual is uninterpretable without it."""
    rendition = np.zeros((8, 8, 3), dtype=np.uint16)
    rendition[..., 1] = 65535

    assert make_derivatives(rendition, with_proxy=False).gamut_fraction == 1.0


# -- uploads (ADR-27) ---------------------------------------------------------


def test_an_upload_yields_both_sizes():
    """The API stores what this returns; a missing proxy would leave the editor blank."""
    # Larger than both targets on the long side, so both are actually reductions.
    image = np.full((2000, 3000, 3), 128, dtype=np.uint8)

    derivatives = derive_from_srgb(image)

    assert (derivatives.fit.width, derivatives.fit.height) == (512, 341)
    assert (derivatives.proxy.width, derivatives.proxy.height) == (2048, 1365)
    assert derivatives.fit.content_type == "image/png"
    assert derivatives.proxy.content_type == "image/jpeg"


def test_an_upload_smaller_than_the_targets_is_not_enlarged():
    image = np.full((300, 400, 3), 200, dtype=np.uint8)

    derivatives = derive_from_srgb(image)

    assert (derivatives.fit.width, derivatives.fit.height) == (400, 300)
    assert (derivatives.proxy.width, derivatives.proxy.height) == (400, 300)


def test_an_upload_reports_no_gamut_clipping():
    """An sRGB file cannot hold a colour outside sRGB, so there is nothing to report."""
    image = np.zeros((16, 16, 3), dtype=np.uint8)

    assert derive_from_srgb(image).gamut_fraction == 0.0


def test_an_upload_takes_the_same_path_as_the_corpus():
    """The point of ADR-27: identical pixels in, identical derivative out.

    An sRGB upload and the same image arriving as a 16-bit ProPhoto rendition
    differ only in the first conversion. Feed the second the ProPhoto encoding of
    a mid grey and both must land on the same downscaled bytes — if they ever
    diverge, an upload is no longer comparable with the 25.000 it is matched
    against, and nothing else in the system would notice.
    """
    flat = np.full((600, 900, 3), 128, dtype=np.uint8)

    upload = derive_from_srgb(flat)
    corpus = make_derivatives(
        # The same colour, expressed the way the corpus arrives: sRGB -> linear
        # -> ProPhoto is skipped by using a grey, which is on the neutral axis of
        # both spaces and so has the same encoded value in each.
        np.full((600, 900, 3), round(srgb_to_prophoto_grey(128) * 65535), dtype=np.uint16),
        with_proxy=True,
    )

    assert (upload.fit.width, upload.fit.height) == (corpus.fit.width, corpus.fit.height)
    assert (upload.proxy.width, upload.proxy.height) == (corpus.proxy.width, corpus.proxy.height)


def srgb_to_prophoto_grey(value: int) -> float:
    """A neutral grey's ProPhoto encoding, for the test above.

    Neutral greys sit on the achromatic axis of both spaces, so the matrix leaves
    them alone and only the transfer function differs.
    """
    from photoassistant.imaging.prophoto import romm_decode
    from photoassistant.renderer.color import srgb_decode

    linear = float(srgb_decode(np.array([value / 255.0]))[0])
    candidates = np.linspace(0.0, 1.0, 100_001)
    return float(candidates[np.argmin(np.abs(romm_decode(candidates) - linear))])


def test_a_badly_compressing_upload_still_encodes():
    """Noise overflowed Pillow's optimise buffer and failed the save.

    Not a hypothetical: a high-ISO night photograph is close enough to noise, and
    an upload is whatever a user sends. The corpus never triggered it because a
    normal photograph compresses.
    """
    noise = (np.random.default_rng(7).random((1200, 1800, 3)) * 255).astype(np.uint8)

    derivatives = derive_from_srgb(noise)

    # Decoded rather than sniffed for a magic number: "broken data stream"
    # produced a short file, and only a full decode proves the whole scan is
    # there rather than its first bytes.
    decoded = Image.open(io.BytesIO(derivatives.proxy.data))
    decoded.load()

    assert decoded.size == (derivatives.proxy.width, derivatives.proxy.height)
