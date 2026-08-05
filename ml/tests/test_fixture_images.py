"""The synthetic test images are present, committed and unchanged in shape.

The renderer tests in the rest of phase 1 and the golden agreement test in 1c all
read these files. They are generated once by ``fixtures/images/generate.py`` and
committed; the generator is not part of any test path, because two
implementations generating their own input would be a second agreement problem.

This file only checks that the set is there and has the shape the tests assume.
What each image is *for* is documented in the generator and in
``docs/notes/phase-1-concepts.md`` §B5.
"""

from pathlib import Path

import pytest
from PIL import Image

IMAGES = Path(__file__).parents[2] / "fixtures" / "images"

# name -> (width, height)
EXPECTED = {
    "clipping_patches": (256, 64),
    "gray_wedge": (256, 64),
    "hue_sweep": (256, 64),
    "noise_block": (64, 64),
    "saturation_ramp": (256, 96),
}


def test_the_expected_images_are_present() -> None:
    found = sorted(path.stem for path in IMAGES.glob("*.png"))
    assert found == sorted(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_image_has_the_expected_size_and_mode(name: str) -> None:
    with Image.open(IMAGES / f"{name}.png") as image:
        assert image.size == EXPECTED[name]
        assert image.mode == "RGB"


def test_the_wedge_carries_every_8_bit_level() -> None:
    """The densest input the curve will see: one column per level, 0 through 255.

    Not every LUT entry — an 8-bit image cannot reach 1024 distinct values. Each
    lookup reads two neighbouring entries, so about half the table is touched.
    """
    with Image.open(IMAGES / "gray_wedge.png") as image:
        top_row = list(image.crop((0, 0, image.width, 1)).get_flattened_data())

    assert [pixel[0] for pixel in top_row] == list(range(256))
    assert all(r == g == b for r, g, b in top_row), "the wedge must be neutral grey"


def test_the_saturation_ramp_spans_grey_to_saturated() -> None:
    """The band vibrance needs: without middle saturation it cannot be told from saturation."""
    with Image.open(IMAGES / "saturation_ramp.png") as image:
        row = list(image.crop((0, 0, image.width, 1)).get_flattened_data())

    def saturation(pixel: tuple[int, int, int]) -> float:
        return (max(pixel) - min(pixel)) / max(max(pixel), 1)

    assert saturation(row[0]) == pytest.approx(0.0, abs=0.01), "starts neutral"
    assert saturation(row[-1]) > 0.95, "ends saturated"

    middle = saturation(row[len(row) // 2])
    assert 0.3 < middle < 0.7, "carries the middle range, which is where vibrance acts"
