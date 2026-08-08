"""The tone curve, its interpolation and its LUT (spec §6).

Most of these assertions are about the *table*, not about any image. That is the
point of the design: the delicate work happens 1024 times in total, so agreement
between the two implementations reduces to comparing two arrays of 1024 numbers —
a question with a yes-or-no answer and no picture involved (notes §B2).
"""

import numpy as np
import pytest

from photoassistant.renderer.curve import (
    LUT_SIZE,
    apply_lut,
    build_lut,
    evaluate,
    is_identity,
    tangents,
)

DIAGONAL = np.array([[0.0, 0.0], [1.0, 1.0]])

# FiveK "Medium Contrast", 12.4% of the catalogue's edits (edit_schema §4).
MEDIUM_CONTRAST = np.array(
    [
        [0.0, 0.0],
        [32 / 255, 22 / 255],
        [64 / 255, 56 / 255],
        [128 / 255, 128 / 255],
        [192 / 255, 196 / 255],
        [1.0, 1.0],
    ]
)

# Deliberately harsh: steep middle segment beside shallow ones, which is what
# makes an uncorrected cubic overshoot.
AGGRESSIVE = np.array([[0.0, 0.0], [0.18, 0.02], [0.35, 0.62], [0.62, 0.66], [1.0, 1.0]])


def _is_monotone(values: np.ndarray, tolerance: float = 1e-9) -> bool:
    return bool(np.all(np.diff(values) >= -tolerance))


@pytest.mark.parametrize(
    "points",
    [
        pytest.param(DIAGONAL, id="diagonal"),
        pytest.param(MEDIUM_CONTRAST, id="FiveK medium contrast"),
        pytest.param(AGGRESSIVE, id="aggressive points"),
    ],
)
def test_the_curve_passes_exactly_through_every_control_point(points: np.ndarray) -> None:
    """Interpolation, not approximation: dragging a point must do what it says."""
    slopes = tangents(points)
    at_knots = evaluate(points, slopes, points[:, 0])

    assert at_knots == pytest.approx(points[:, 1], abs=1e-12)


@pytest.mark.parametrize(
    "points",
    [
        pytest.param(DIAGONAL, id="diagonal"),
        pytest.param(MEDIUM_CONTRAST, id="FiveK medium contrast"),
        pytest.param(AGGRESSIVE, id="aggressive points"),
    ],
)
def test_the_table_is_monotone(points: np.ndarray) -> None:
    """A dip would invert a gradient — a visible band, not a rounding matter."""
    assert _is_monotone(build_lut(points).astype(np.float64))


def test_the_correction_actually_fires_on_the_aggressive_points() -> None:
    """Guards the previous test: monotonicity that never needed enforcing proves little.

    Without a case where the raw three-point tangents overshoot, the
    Fritsch-Carlson step could be missing entirely and every test would still
    pass.
    """
    x = AGGRESSIVE[:, 0]
    y = AGGRESSIVE[:, 1]
    secants = np.diff(y) / np.diff(x)

    raw = np.empty(len(AGGRESSIVE))
    raw[0], raw[-1] = secants[0], secants[-1]
    raw[1:-1] = (secants[:-1] + secants[1:]) / 2.0

    corrected = tangents(AGGRESSIVE)

    assert not np.allclose(raw, corrected), "the correction left the tangents untouched"

    # And after correcting, every segment sits inside the radius-3 circle.
    for i in range(len(AGGRESSIVE) - 1):
        if secants[i] == 0.0:
            continue
        alpha = corrected[i] / secants[i]
        beta = corrected[i + 1] / secants[i]
        assert alpha**2 + beta**2 <= 9.0 + 1e-9


def test_a_flat_segment_stays_flat() -> None:
    points = np.array([[0.0, 0.0], [0.3, 0.5], [0.7, 0.5], [1.0, 1.0]])

    slopes = tangents(points)

    assert slopes[1] == 0.0
    assert slopes[2] == 0.0
    samples = evaluate(points, slopes, np.linspace(0.3, 0.7, 50))
    assert samples == pytest.approx(0.5, abs=1e-12)


def test_the_table_has_the_size_the_spec_fixes() -> None:
    assert LUT_SIZE == 1024
    assert len(build_lut(MEDIUM_CONTRAST)) == 1024


def test_the_ends_of_the_table_hit_the_ends_of_the_curve() -> None:
    """Sampling at i/(N-1) is what makes lut[0] and lut[-1] exact, not approximate."""
    lut = build_lut(np.array([[0.0, 0.08], [0.5, 0.5], [1.0, 0.95]]))

    assert float(lut[0]) == pytest.approx(0.08, abs=1e-6)
    assert float(lut[-1]) == pytest.approx(0.95, abs=1e-6)


def test_the_diagonal_is_the_identity_table() -> None:
    lut = build_lut(DIAGONAL)

    assert lut == pytest.approx(np.linspace(0.0, 1.0, LUT_SIZE), abs=1e-6)


def test_lookup_agrees_with_the_curve_it_samples() -> None:
    """The approximation error of the table, measured rather than assumed.

    A 1024-entry table spaced over [0, 1] steps by 0.00098, well under the 8-bit
    output step of 1/255 = 0.0039, so the error disappears in quantisation.
    """
    slopes = tangents(MEDIUM_CONTRAST)
    lut = build_lut(MEDIUM_CONTRAST)

    x = np.linspace(0.0, 1.0, 501, dtype=np.float32)
    exact = evaluate(MEDIUM_CONTRAST, slopes, x.astype(np.float64))
    through_table = apply_lut(lut, x).astype(np.float64)

    worst = float(np.max(np.abs(exact - through_table)))
    assert worst < 1.0 / 255.0 / 4.0, f"table error {worst:.2e} is not negligible at 8 bits"


def test_lookup_clips_its_input() -> None:
    """After the tone regions and contrast a value may leave [0, 1]; the index cannot."""
    lut = build_lut(MEDIUM_CONTRAST)

    assert float(apply_lut(lut, np.float32(-0.5))) == pytest.approx(float(lut[0]), abs=1e-6)
    assert float(apply_lut(lut, np.float32(1.5))) == pytest.approx(float(lut[-1]), abs=1e-6)


def test_lookup_works_over_an_image() -> None:
    lut = build_lut(MEDIUM_CONTRAST)
    image = np.full((3, 4, 3), 0.5, dtype=np.float32)

    assert apply_lut(lut, image).shape == (3, 4, 3)


def test_identity_recognises_only_the_diagonal() -> None:
    assert is_identity(DIAGONAL)
    assert not is_identity(MEDIUM_CONTRAST)
    lifted_black = np.array([[0.0, 0.1], [1.0, 1.0]])
    assert not is_identity(lifted_black), "a lifted black point is not the identity"
