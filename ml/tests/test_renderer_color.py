"""The transfer function and luma (spec §2).

These two sit under everything else: an error here shifts every operation that
runs in the wrong space, and would look like a fault in whichever slider was
being examined at the time.
"""

import numpy as np
import pytest

from photoassistant.renderer.color import luma, srgb_decode, srgb_encode


def test_decode_and_encode_are_inverse() -> None:
    values = np.linspace(0.0, 1.0, 257, dtype=np.float32)

    assert srgb_encode(srgb_decode(values)) == pytest.approx(values, abs=1e-6)


def test_the_endpoints_are_fixed() -> None:
    assert float(srgb_decode(np.float32(0.0))) == pytest.approx(0.0, abs=1e-9)
    assert float(srgb_decode(np.float32(1.0))) == pytest.approx(1.0, abs=1e-6)
    assert float(srgb_encode(np.float32(0.0))) == pytest.approx(0.0, abs=1e-9)
    assert float(srgb_encode(np.float32(1.0))) == pytest.approx(1.0, abs=1e-6)


def test_the_piecewise_join_is_continuous() -> None:
    """Both branches agree at the breakpoint, which is what makes the curve smooth."""
    linear_branch = 0.04045 / 12.92
    power_branch = ((0.04045 + 0.055) / 1.055) ** 2.4

    assert linear_branch == pytest.approx(power_branch, abs=1e-7)
    assert float(srgb_decode(np.float32(0.04045))) == pytest.approx(0.0031308, abs=1e-6)


def test_it_is_not_the_2_2_power_approximation() -> None:
    """The reason spec §2.1 spells the function out (see notes §B1).

    The ratio between file values 100 and 200 is ~4.53 under the real transfer
    function and 2^2.2 = 4.595 under the approximation. The gap is small, but it
    is systematic and largest in the shadows, so it would eat the ΔE budget
    before any operation had done anything.
    """
    ratio = float(srgb_decode(np.float32(200 / 255)) / srgb_decode(np.float32(100 / 255)))

    assert ratio == pytest.approx(4.53, abs=0.01)
    assert ratio != pytest.approx(2.0**2.2, abs=0.01)


def test_decoding_continues_above_white() -> None:
    """Exposure pushes past 1 and only step 11 clips, so neither direction saturates."""
    assert float(srgb_encode(np.float32(4.0))) > 1.0
    assert float(srgb_encode(np.float32(32.0))) > float(srgb_encode(np.float32(4.0)))


def test_luma_of_grey_is_the_grey_value() -> None:
    """The weights sum to 1, so a neutral pixel maps to itself."""
    for level in (0.0, 0.25, 0.5, 0.75, 1.0):
        grey = np.array([level, level, level], dtype=np.float32)
        assert float(luma(grey)) == pytest.approx(level, abs=1e-6)


def test_luma_makes_saturated_blue_dark() -> None:
    """Blue contributes 7.2% of luma, so a vivid blue reads as a dark pixel.

    Not a defect — a consequence of the metric, and the reason the blacks mask
    reaches into saturated blues (notes §B3). Pinned here so the behaviour is
    deliberate rather than discovered again.
    """
    blue = float(luma(np.array([0.0, 0.0, 1.0], dtype=np.float32)))
    green = float(luma(np.array([0.0, 1.0, 0.0], dtype=np.float32)))

    assert blue == pytest.approx(0.0722, abs=1e-6)
    assert green == pytest.approx(0.7152, abs=1e-6)
    assert blue < 0.25, "fully saturated blue sits inside the blacks region"


def test_luma_works_over_an_image() -> None:
    image = np.zeros((4, 5, 3), dtype=np.float32)
    image[..., :] = 0.4

    assert luma(image).shape == (4, 5)
    assert np.allclose(luma(image), 0.4, atol=1e-6)
