"""Tone-region masks (spec §7).

The numbers asserted here are the ones printed in the specification's table, so
this file is also the check that the spec and the code still say the same thing.
"""

import numpy as np
import pytest

from photoassistant.renderer.masks import blacks, highlights, shadows, smoothstep, whites

ALL_MASKS = (
    ("blacks", blacks),
    ("shadows", shadows),
    ("highlights", highlights),
    ("whites", whites),
)

# Table from RENDERER_SPEC.md §7.3.
SPEC_TABLE = {
    0.00: (1.0000, 0.0000, 0.0000, 0.0000),
    0.25: (0.0000, 1.0000, 0.0000, 0.0000),
    0.50: (0.0000, 0.1983, 0.1983, 0.0000),
    0.75: (0.0000, 0.0000, 1.0000, 0.0000),
    1.00: (0.0000, 0.0000, 0.0000, 1.0000),
}


@pytest.mark.parametrize("y", sorted(SPEC_TABLE), ids=[f"Y={y:.2f}" for y in sorted(SPEC_TABLE)])
def test_the_masks_match_the_specification_table(y: float) -> None:
    value = np.float32(y)
    measured = (
        float(blacks(value)),
        float(shadows(value)),
        float(highlights(value)),
        float(whites(value)),
    )

    assert measured == pytest.approx(SPEC_TABLE[y], abs=5e-5)


def test_blacks_and_shadows_hand_over_without_a_gap() -> None:
    """w_blacks + w_shadows is exactly 1 across [0, 0.25].

    Two regions sharing an end of the range pass the weight between them with no
    hole and no double coverage — which is what a hard threshold cannot do.
    """
    y = np.linspace(0.0, 0.25, 200, dtype=np.float32)

    assert blacks(y) + shadows(y) == pytest.approx(np.ones_like(y), abs=1e-6)


def test_highlights_and_whites_hand_over_without_a_gap() -> None:
    y = np.linspace(0.75, 1.0, 200, dtype=np.float32)

    assert highlights(y) + whites(y) == pytest.approx(np.ones_like(y), abs=1e-6)


def test_the_midtones_are_protected() -> None:
    """Total weight dips to 0.3965 at mid grey: the middle belongs to curve and contrast."""
    y = np.float32(0.5)
    total = float(blacks(y) + shadows(y) + highlights(y) + whites(y))

    assert total == pytest.approx(0.3965, abs=1e-3)


@pytest.mark.parametrize("mask", [m for _, m in ALL_MASKS], ids=[n for n, _ in ALL_MASKS])
def test_every_mask_stays_a_weight(mask) -> None:
    y = np.linspace(0.0, 1.0, 1001, dtype=np.float32)
    values = mask(y)

    assert float(values.min()) >= 0.0
    assert float(values.max()) <= 1.0 + 1e-6


@pytest.mark.parametrize("mask", [m for _, m in ALL_MASKS], ids=[n for n, _ in ALL_MASKS])
def test_every_mask_is_continuous(mask) -> None:
    """A jump would show as a visible band along a line of constant luma."""
    y = np.linspace(0.0, 1.0, 4001, dtype=np.float32)
    steps = np.abs(np.diff(mask(y).astype(np.float64)))

    # With 4000 samples over the range, no single step may be a visible fraction
    # of the whole weight.
    assert float(steps.max()) < 0.01


def test_each_mask_covers_its_own_end_of_the_range() -> None:
    assert float(blacks(np.float32(0.0))) == pytest.approx(1.0, abs=1e-6)
    assert float(blacks(np.float32(0.5))) == pytest.approx(0.0, abs=1e-6)

    assert float(whites(np.float32(1.0))) == pytest.approx(1.0, abs=1e-6)
    assert float(whites(np.float32(0.5))) == pytest.approx(0.0, abs=1e-6)

    assert float(shadows(np.float32(0.7))) == pytest.approx(0.0, abs=1e-6)
    assert float(highlights(np.float32(0.3))) == pytest.approx(0.0, abs=1e-6)


def test_above_white_the_range_belongs_entirely_to_whites() -> None:
    """Between steps 4 and 11 a luma may exceed 1, and the masks clamp there.

    Highlights has closed by then and whites is fully open, so a pixel blown past
    white is reachable by ``whites`` alone. Pinned because it is not obvious from
    the formulas and it constrains what phase 2 can fit — see
    ``test_renderer_pipeline.py`` and notes §B3.
    """
    for y in (1.0, 1.2, 4.0):
        value = np.float32(y)
        assert float(highlights(value)) == 0.0
        assert float(whites(value)) == 1.0
        assert float(blacks(value)) == 0.0
        assert float(shadows(value)) == 0.0


def test_smoothstep_is_flat_at_both_ends() -> None:
    """The property that lets masks meet without a kink."""
    assert float(smoothstep(0.0, 1.0, np.float32(0.0))) == pytest.approx(0.0, abs=1e-9)
    assert float(smoothstep(0.0, 1.0, np.float32(1.0))) == pytest.approx(1.0, abs=1e-9)
    assert float(smoothstep(0.0, 1.0, np.float32(0.5))) == pytest.approx(0.5, abs=1e-6)

    # Derivative approaching zero at the edges: the first step away from 0 is far
    # smaller than a linear ramp's would be.
    assert float(smoothstep(0.0, 1.0, np.float32(0.01))) < 0.001


def test_smoothstep_clamps_outside_its_window() -> None:
    assert float(smoothstep(0.25, 0.75, np.float32(0.1))) == 0.0
    assert float(smoothstep(0.25, 0.75, np.float32(0.9))) == 1.0
