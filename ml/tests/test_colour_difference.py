"""CIEDE2000 checked against the published reference pairs.

Sharma, Wu & Dalal, "The CIEDE2000 color-difference formula: Implementation
notes, supplementary test data, and mathematical observations", Color Research &
Application 30(1), 2005, pp. 21-30.

The paper publishes 34 Lab pairs chosen to land on the discontinuities where a
naive implementation goes wrong — hue angles wrapping past 360, the mean hue with
one chroma at zero, the near-neutral region where the G correction matters.

This test exists because **ΔE is the measuring instrument of the whole phase**.
If it is subtly wrong, the golden test either passes when it should not or fails
for no reason, and the search would go looking in the renderer while the fault is
in the ruler. Checking the ruler against published values first removes that
entire class of confusion, and costs one test.

Note what this does and does not prove: it proves the formula is implemented as
published. It says nothing about whether ΔE is the right metric for our purpose —
that is a modelling choice, argued in ``docs/notes/phase-1-concepts.md`` §B6.
"""

import numpy as np
import pytest

from photoassistant.renderer.color import ciede2000, delta_e, srgb_to_lab

# (L1, a1, b1), (L2, a2, b2), expected ΔE00 — table 1 of the paper.
SHARMA_PAIRS: list[tuple[tuple[float, float, float], tuple[float, float, float], float]] = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0010, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


def test_the_reference_table_is_complete() -> None:
    """Guards the test: a truncated table would still pass every case in it."""
    assert len(SHARMA_PAIRS) == 34


@pytest.mark.parametrize(
    ("lab1", "lab2", "expected"),
    SHARMA_PAIRS,
    ids=[f"pair {i + 1:02d}" for i in range(len(SHARMA_PAIRS))],
)
def test_matches_the_published_value(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
    expected: float,
) -> None:
    result = ciede2000(np.array(lab1), np.array(lab2))

    # The paper prints four decimals, so agreement to that precision is the most
    # the data can assert.
    assert float(result) == pytest.approx(expected, abs=5e-5)


def test_the_metric_is_symmetric() -> None:
    """ΔE00(a, b) = ΔE00(b, a) — which is why only one implementation is needed.

    Pairs 7 and 8 of the table are the same colours in both orders and carry the
    same published value, so the property is in the reference data as well.
    """
    for lab1, lab2, _ in SHARMA_PAIRS:
        forward = ciede2000(np.array(lab1), np.array(lab2))
        backward = ciede2000(np.array(lab2), np.array(lab1))
        assert float(forward) == pytest.approx(float(backward), abs=1e-12)


def test_identical_colours_have_zero_difference() -> None:
    for lab, _, _ in SHARMA_PAIRS:
        assert float(ciede2000(np.array(lab), np.array(lab))) == pytest.approx(0.0, abs=1e-12)


def test_it_vectorises_over_an_image() -> None:
    """The golden test compares whole images, so the metric has to broadcast."""
    lab1 = np.array([[pair[0] for pair in SHARMA_PAIRS[:4]]])
    lab2 = np.array([[pair[1] for pair in SHARMA_PAIRS[:4]]])

    result = ciede2000(lab1, lab2)

    assert result.shape == (1, 4)
    for i, (_, _, expected) in enumerate(SHARMA_PAIRS[:4]):
        assert float(result[0, i]) == pytest.approx(expected, abs=5e-5)


def test_known_srgb_colours_convert_to_lab() -> None:
    """Anchors the sRGB to Lab path, which the reference pairs do not exercise."""
    lab = srgb_to_lab(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.5, 0.5, 0.5]]))

    assert lab[0] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert lab[1] == pytest.approx([100.0, 0.0, 0.0], abs=1e-4)

    # Mid grey stays neutral. The tolerance is 1e-4 rather than 0 because the
    # published sRGB-to-XYZ matrix is rounded to seven decimals: its middle row
    # sums to 1.0000001 instead of 1, while the X and Z rows reproduce the white
    # point exactly. For a neutral input that mismatch survives into a*, scaled
    # by the factor 500 in the Lab formula, and lands around 1e-5.
    #
    # The matrix is left as published. Renormalising its rows would put us a
    # rounding step away from every other implementation, to fix a deviation four
    # orders of magnitude below the threshold of perception.
    assert lab[2][1] == pytest.approx(0.0, abs=1e-4)
    assert lab[2][2] == pytest.approx(0.0, abs=1e-4)

    # What actually matters: the residue is nowhere near visible.
    neutral_shift = ciede2000(lab[2], np.array([lab[2][0], 0.0, 0.0]))
    assert float(neutral_shift) < 1e-4


def test_delta_e_over_identical_images_is_zero() -> None:
    image = np.array([[[0.2, 0.4, 0.6], [0.9, 0.1, 0.3]]], dtype=np.float32)

    assert np.max(delta_e(image, image)) == pytest.approx(0.0, abs=1e-12)
