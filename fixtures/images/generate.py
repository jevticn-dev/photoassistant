"""Generate the synthetic test images used by the renderer tests.

Run once; the resulting PNGs are committed and every implementation reads the
same files:

    uv run --project ml python fixtures/images/generate.py

The script is **not** part of any test path. Were both implementations to
generate their input at test time, the generator itself would become a second
agreement problem, in the exact place we are trying to remove one.

Why synthetic rather than photographs. The golden test asks whether the two
implementations agree, not whether an edit looks good, and for that question a
deliberately built image beats a photograph: it covers the parameter space on
purpose instead of by chance, it is byte-identical on every machine, and it
raises no licensing question in a public repository (the FiveK images may not be
redistributed; they are used locally, never committed).

Each image earns its place by making one thing testable:

===================== ===============================================
Image                 What it lets a test see
===================== ===============================================
gray_wedge            the curve and its LUT, the tone-region masks
hue_sweep             white balance, saturation
saturation_ramp       vibrance — see the note below
clipping_patches      whites, blacks, highlights, shadows, clipping
noise_block           behaviour with no structure to hide artefacts
===================== ===============================================

The saturation ramp is required, not decorative. Vibrance is defined to spare
already-saturated pixels (its share of the effect is ``1 - p``), so it acts most
strongly on *moderately* saturated colour. An image made only of neutral grey and
near-fully-saturated hues cannot distinguish a correct vibrance from a plain
saturation — the selectivity is the only difference between them, and nothing in
such an image exercises it. Found while reviewing the specification on
2026-08-05; see ``docs/notes/phase-1-concepts.md`` §B5.

One honest limit: an 8-bit image carries at most 256 distinct values per channel,
so the wedge exercises all 256 possible inputs, not all 1024 LUT entries. Each
lookup reads two neighbouring entries, so roughly half the table is touched. Full
LUT coverage would need a higher bit depth, which the editor pipeline does not
use.
"""

import random
from pathlib import Path

from PIL import Image

OUT = Path(__file__).parent

WIDTH = 256
BAND = 32

# Fixed so a regenerated file is byte-identical to the committed one.
NOISE_SEED = 20260805


def _hsl_to_rgb(hue: float, saturation: float, lightness: float) -> tuple[int, int, int]:
    """HSL to 8-bit sRGB. Plain arithmetic, so the values are easy to check by hand."""
    chroma = (1.0 - abs(2.0 * lightness - 1.0)) * saturation
    sector = (hue % 360.0) / 60.0
    second = chroma * (1.0 - abs(sector % 2.0 - 1.0))

    if sector < 1.0:
        rgb = (chroma, second, 0.0)
    elif sector < 2.0:
        rgb = (second, chroma, 0.0)
    elif sector < 3.0:
        rgb = (0.0, chroma, second)
    elif sector < 4.0:
        rgb = (0.0, second, chroma)
    elif sector < 5.0:
        rgb = (second, 0.0, chroma)
    else:
        rgb = (chroma, 0.0, second)

    offset = lightness - chroma / 2.0
    return tuple(round((channel + offset) * 255.0) for channel in rgb)  # type: ignore[return-value]


def _save(name: str, size: tuple[int, int], pixels: list[tuple[int, int, int]]) -> None:
    image = Image.new("RGB", size)
    image.putdata(pixels)
    image.save(OUT / name, optimize=True)
    print(f"  {name:<24} {size[0]}x{size[1]}")


def gray_wedge() -> None:
    """Every 8-bit grey level, one column each — the densest input the curve will ever see."""
    height = BAND * 2
    row = [(value, value, value) for value in range(WIDTH)]
    _save("gray_wedge.png", (WIDTH, height), row * height)


def hue_sweep() -> None:
    """The full hue circle at constant saturation and lightness."""
    height = BAND * 2
    row = [_hsl_to_rgb(x / WIDTH * 360.0, 0.85, 0.5) for x in range(WIDTH)]
    _save("hue_sweep.png", (WIDTH, height), row * height)


def saturation_ramp() -> None:
    """Three hues, each going from neutral grey to fully saturated.

    This is the image that makes vibrance testable: the middle of every band is
    where the ``1 - p`` weighting has most of its effect.
    """
    hues = (20.0, 140.0, 260.0)
    pixels: list[tuple[int, int, int]] = []
    for hue in hues:
        row = [_hsl_to_rgb(hue, x / (WIDTH - 1), 0.5) for x in range(WIDTH)]
        pixels.extend(row * BAND)
    _save("saturation_ramp.png", (WIDTH, BAND * len(hues)), pixels)


def clipping_patches() -> None:
    """Flat blocks at and next to both ends of the range.

    Values 1 and 254 sit beside 0 and 255 on purpose: they tell a clipping bug
    apart from a rounding one, which a block of pure black or white cannot.
    """
    grays = (0, 1, 8, 64, 128, 192, 254, 255)
    colours = (
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (0, 0, 0),
        (255, 255, 255),
    )
    block = WIDTH // len(grays)

    top = [(value, value, value) for value in grays for _ in range(block)]
    bottom = [colour for colour in colours for _ in range(block)]

    _save("clipping_patches.png", (WIDTH, BAND * 2), top * BAND + bottom * BAND)


def noise_block() -> None:
    """Unstructured pixels, so an artefact has nothing to hide behind."""
    rng = random.Random(NOISE_SEED)
    size = 64
    pixels = [
        (rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(size * size)
    ]
    _save("noise_block.png", (size, size), pixels)


def main() -> None:
    print(f"writing test images to {OUT}")
    gray_wedge()
    hue_sweep()
    saturation_ramp()
    clipping_patches()
    noise_block()


if __name__ == "__main__":
    main()
