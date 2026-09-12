"""Look at the fits, because the average error cannot (phase 2, task 6).

    uv run --project ml python -m pipeline.contact_sheets
    uv run --project ml python -m pipeline.contact_sheets --count 8

Writes one sheet per edit into the work directory: the starting image, our
reconstruction, the expert's result, and a heat map of where the two differ.

**Why this exists at all, when there are numbers.** Twice in phase 1 the thing
that mattered was invisible to every number being reported. A mean ΔE of 8.00
looked like an ordinary bad fit; the contact sheet showed the image was nearly
black and white, because the white balance could not reach far enough and the
optimiser had drained the saturation instead. That produced ADR-19. A mean is one
number over a million pixels, and it cannot distinguish "slightly wrong
everywhere" from "catastrophically wrong in one respect".

So the five best and five worst get looked at, every time the fitting changes.

**Nothing here is committed.** The sheets contain FiveK imagery, the licence is
research-only, and the repository is public (`.claude/rules/pipeline.md`). They
land in the work directory, which is git-ignored, and can be regenerated in
seconds.
"""

import argparse
import os
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from photoassistant.renderer import delta_e, quantise, render
from photoassistant.schema import EditRecipe
from photoassistant.storage import DatabaseConfig, connect
from PIL import Image, ImageDraw

from pipeline.analyse_fits import read_examples
from pipeline.environment import REPOSITORY_ROOT, load
from pipeline.fit_all import load_image, store

LABEL_HEIGHT = 18
GAP = 6

# Above this many ΔE a difference is unmistakable; the heat map saturates there
# so that the interesting range is not compressed into the top of the scale.
HEAT_CEILING = 10.0


def heat_map(difference: NDArray[np.floating]) -> NDArray[np.uint8]:
    """Per-pixel ΔE as an image: black where we match, red where we do not.

    A picture of the error rather than a summary of it. A uniform wash means the
    model is a little off everywhere; a bright patch means it failed at one thing,
    and those are the two cases a mean cannot tell apart.
    """
    scaled = np.clip(np.asarray(difference) / HEAT_CEILING, 0.0, 1.0)
    out = np.zeros((*scaled.shape, 3), dtype=np.uint8)
    out[..., 0] = (scaled * 255).astype(np.uint8)
    out[..., 1] = (np.clip(scaled * 2 - 1, 0, 1) * 255).astype(np.uint8)
    return out


def sheet(panels: list[tuple[str, NDArray[np.uint8]]], title: str) -> Image.Image:
    height = max(panel.shape[0] for _, panel in panels)
    width = sum(panel.shape[1] for _, panel in panels) + GAP * (len(panels) - 1)

    canvas = Image.new("RGB", (width, height + LABEL_HEIGHT * 2), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 4), title, fill=(235, 235, 235))

    x = 0
    for label, panel in panels:
        canvas.paste(Image.fromarray(panel), (x, LABEL_HEIGHT))
        draw.text((x + 4, LABEL_HEIGHT + height + 2), label, fill=(190, 190, 190))
        x += panel.shape[1] + GAP
    return canvas


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=5, help="how many at each end")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    load()

    with connect(DatabaseConfig.from_environment()) as connection:
        rows = read_examples(connection)

    if not rows:
        print("no fitted examples in the database")
        return

    ordered = sorted(rows, key=lambda row: row["fit_error"])
    chosen = [("best", row) for row in ordered[: arguments.count]]
    chosen += [("worst", row) for row in ordered[-arguments.count :]]

    destination = Path(
        os.environ.get("SHEETS_DIR", REPOSITORY_ROOT / "pipeline/.work/sheets")
    )
    destination.mkdir(parents=True, exist_ok=True)

    bucket = store().derivatives
    print(f"{'':6} {'photograph':38} {'expert':>7} {'dE':>7}")

    for kind, row in chosen:
        reference, expert = row["reference"], row["expert"]
        before = load_image(bucket, f"fivek/{reference}/pre512.png")
        after = load_image(bucket, f"fivek/{reference}/after512-{expert}.png")
        ours = render(before, EditRecipe.model_validate(row["edit"]))

        panels = [
            ("before (InputAsShotZeroed)", quantise(before)),
            ("ours", quantise(ours)),
            (f"expert {expert.upper()}", quantise(after)),
            (f"difference, 0 to {HEAT_CEILING:.0f} dE", heat_map(delta_e(ours, after))),
        ]
        title = f"{kind}  {reference}  expert {expert.upper()}  mean dE {row['fit_error']:.2f}"

        name = f"{kind}-{row['fit_error']:06.3f}-{reference}-{expert}.png"
        sheet(panels, title).save(destination / name, optimize=True)
        print(f"{kind:6} {reference[:38]:38} {expert:>7} {row['fit_error']:>7.2f}")

    print(f"\n{len(chosen)} sheets written to {destination}")
    print("Not committed: FiveK imagery, research-only licence, public repository.")


if __name__ == "__main__":
    main()
