"""Contact sheets for the best and worst reconstructions (phase 1b, ADR-16).

    uv run --project ml python pipeline/probe/visuals.py

A mean ΔE says how far off the fit is. It does not say **where** or **how** — a
uniform half-stop miss and a blown sky with everything else perfect can produce
the same number, and they call for different fixes.

Each sheet is four panels:

    start | our reconstruction | the expert | where the error is

The fourth panel is the per-pixel ΔE as a heat map, on a fixed scale so sheets
are comparable: black is a match, white is ΔE 10 or worse.

Output goes to the work directory, **not** into the repository. FiveK renditions
are licensed for research use only and the repository is public
(`.claude/rules/pipeline.md`); the sheets regenerate from the committed sample in
one command.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from photoassistant.renderer.color import delta_e
from photoassistant.renderer.pipeline import quantise, render
from photoassistant.schema import EditRecipe
from PIL import Image, ImageDraw

MEASURED = Path(__file__).parent / "measure_report.json"

HOW_MANY = 5
HEAT_CEILING = 10.0  # ΔE that maps to white in the error panel
GAP = 8
LABEL_HEIGHT = 16


def work_root() -> Path:
    configured = os.environ.get("PROBE_WORK_DIR")
    return Path(configured) if configured else Path(__file__).parents[2] / "pipeline" / ".work"


def heat_map(difference: NDArray[np.floating]) -> NDArray[np.uint8]:
    """ΔE to greyscale on a fixed scale, so two sheets can be compared."""
    scaled = np.clip(np.asarray(difference) / HEAT_CEILING, 0.0, 1.0)
    return np.repeat((scaled * 255).astype(np.uint8)[..., np.newaxis], 3, axis=-1)


def sheet(panels: list[tuple[str, NDArray[np.uint8]]], title: str) -> Image.Image:
    height, width = panels[0][1].shape[:2]
    canvas = Image.new(
        "RGB",
        (width * len(panels) + GAP * (len(panels) - 1), height + LABEL_HEIGHT * 2),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((2, 2), title, fill=(235, 235, 235))

    for index, (label, image) in enumerate(panels):
        x = index * (width + GAP)
        canvas.paste(Image.fromarray(image), (x, LABEL_HEIGHT))
        draw.text((x + 2, LABEL_HEIGHT + height + 2), label, fill=(185, 185, 185))
    return canvas


def main() -> None:
    if not MEASURED.is_file():
        sys.exit(f"missing {MEASURED} — run measure.py first")

    rows = json.loads(MEASURED.read_text(encoding="utf-8"))["photos"]
    ranked = sorted(rows, key=lambda row: float(row["curve_from_theirs"]))
    chosen = [("best", row) for row in ranked[:HOW_MANY]]
    chosen += [("worst", row) for row in ranked[-HOW_MANY:]]

    root = work_root()
    out = root / "sheets"
    out.mkdir(parents=True, exist_ok=True)

    for rank, (kind, row) in enumerate(chosen, start=1):
        name = row["basename"]
        start = np.load(root / "reference" / f"{name}.npy")
        expert = np.load(root / "after" / f"{name}.npy")

        recipe = EditRecipe.model_validate(row["recipe"])
        reconstructed = render(start, recipe)
        difference = delta_e(reconstructed, expert)

        position = rank if kind == "best" else rank - HOW_MANY
        title = (
            f"{kind} {position}  {name}   "
            f"start dE {row['untouched_from_theirs']}  ->  fitted dE {row['curve_from_theirs']}"
        )
        panels = [
            ("start (Lightroom neutral)", quantise(start)),
            ("our reconstruction", quantise(reconstructed)),
            ("expert C", quantise(expert)),
            (f"error, white = dE {HEAT_CEILING:.0f}", heat_map(difference)),
        ]
        target = out / f"{kind}-{position}-{name}.png"
        sheet(panels, title).save(target, optimize=True)
        print(
            f"  {kind:<5} {position}  {name:<40} "
            f"dE {row['curve_from_theirs']:5.2f}  -> {target.name}"
        )

    print()
    print(f"{len(chosen)} sheets -> {out}")
    print("Not committed: FiveK renditions are research-licensed and the repository is public.")


if __name__ == "__main__":
    main()
