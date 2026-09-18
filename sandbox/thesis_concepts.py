"""Conceptual figures for the thesis, labelled in Serbian Cyrillic.

    uv run --project ml --extra service python -m sandbox.thesis_concepts

Separate from `sandbox/thesis_figures.py`, and the split is the point rather than
an oversight. That module draws **measured data**: it needs the database, MinIO
and the JSON reports, and every number in it came out of a run. This one draws
the **formulas the renderer itself executes** — masks, the curve, the transfer
function, the colour-space matrices — so it needs nothing but the library.

That matters for what the figures are worth. A mask drawn from the specification
by hand would illustrate the specification; a mask drawn by calling
`renderer.masks` illustrates what the system actually does, and drifts the moment
the code drifts. Same for the gamut figure, whose primaries are derived from the
matrices in `imaging/prophoto.py` rather than copied from a standard.

Theory chapter figures that are diagrams rather than plots (CIELAB axes, HNSW,
the ER diagram) are hand-written SVG next to the existing ones, for the same
reason `arhitektura.svg` is: there is no data to plot.

**Output is not committed** — `docs/thesis/` is in `.git/info/exclude`. None of
these contain FiveK imagery, but they live beside figures that do.
"""

import os
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

# The progress lines are Cyrillic and the Windows console defaults to cp1252,
# which cannot encode them — the script would die on its own `print`, after
# doing the work. Nothing about the figures depends on this.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib.pyplot as plt  # noqa: E402
from photoassistant.imaging.prophoto import (  # noqa: E402
    _ROMM_TO_XYZ_D50,
    _XYZ_D65_TO_SRGB,
)
from photoassistant.renderer import build_lut, masks, srgb_decode  # noqa: E402

from pipeline.environment import REPOSITORY_ROOT  # noqa: E402

FIGURES = Path(os.environ.get("THESIS_FIGURES") or REPOSITORY_ROOT / "docs/thesis/figures")
BLUE, PALE, DARK, RED = "#3b6ea5", "#b8c9dd", "#1f4e79", "#cc4444"
GREEN, ORANGE, GREY = "#4a7c59", "#d08c3f", "#777777"


def sr(value: float, decimals: int = 2) -> str:
    """Serbian decimal comma."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _comma(value: float, _position: int) -> str:
    """Tick labels with the decimal comma, as the rest of the document uses."""
    text = f"{value:g}"
    return text.replace(".", ",")


def style(axes) -> None:
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.grid(alpha=0.25, linewidth=0.6)
    axes.set_axisbelow(True)
    formatter = matplotlib.ticker.FuncFormatter(_comma)
    axes.xaxis.set_major_formatter(formatter)
    axes.yaxis.set_major_formatter(formatter)


def save(figure, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURES / name, dpi=200, bbox_inches="tight")
    plt.close(figure)
    print(f"  {name}")


# -- chapter 2.1: light --------------------------------------------------------


def transfer_function() -> None:
    """The sRGB transfer function against the power-2.2 approximation.

    Spec §2.1 forbids the approximation, and the reason is not that the error is
    large but that it is **systematic and worst in the shadows** — exactly where
    tonal work happens. A single curve plot hides that, because both curves look
    identical at this scale; the relative error panel is what carries the point.
    """
    stored = np.linspace(0.0, 1.0, 1001, dtype=np.float32)
    exact = srgb_decode(stored)
    approximate = np.power(stored, 2.2, dtype=np.float32)

    figure, (left, right) = plt.subplots(1, 2, figsize=(10.5, 4.2))

    left.plot(stored, exact, color=BLUE, linewidth=2.0, label="sRGB, део по део")
    left.plot(stored, approximate, color=RED, linewidth=1.4, linestyle="--",
              label="апроксимација степеном 2,2")
    left.set_xlabel("вредност у фајлу")
    left.set_ylabel("количина светла (линеарно)")
    left.set_title("На овој скали разлика се не види")
    # The curve is convex, so the upper-left corner is the only region it leaves
    # empty. The legend goes there and the ratio note goes bottom-right, below
    # the curve; putting either near the middle puts it on top of the curve.
    left.legend(frameon=False, fontsize=8.5, loc="upper left", handlelength=1.6)
    left.set_xlim(0, 1)
    left.set_ylim(0, 1)
    style(left)

    # Relative error, which is where the difference actually lives.
    with np.errstate(divide="ignore", invalid="ignore"):
        relative = np.where(exact > 0, (approximate - exact) / exact * 100.0, np.nan)
    right.plot(stored, relative, color=DARK, linewidth=1.8)
    right.axhline(0.0, color=GREY, linewidth=1.0)
    right.set_xlabel("вредност у фајлу")
    right.set_ylabel("одступање апроксимације (%)")
    right.set_title("Одступање је систематско и највеће у тамним тоновима")
    right.set_xlim(0, 1)
    right.set_ylim(-70, 10)
    style(right)

    # The two values the concept note carries, so the figure and the text agree.
    for value, label, offset in (
        (100 / 255, "100/255", (-0.06, 0.13)),
        (200 / 255, "200/255", (-0.06, 0.13)),
    ):
        light = float(srgb_decode(np.float32(value)))
        left.plot([value], [light], marker="o", markersize=5, color=DARK)
        left.annotate(f"{label} → {sr(light, 3)}", xy=(value, light),
                      xytext=(value + offset[0], light + offset[1]),
                      fontsize=8.5, color=DARK, ha="right",
                      arrowprops={"arrowstyle": "-", "color": DARK, "linewidth": 0.7})

    # Two decimals, not three: `srgb_decode` works in float32 and gives 4,532
    # where the concept note's float64 figure is 4,531. Rounding one place
    # earlier is true in both precisions, and the point does not need the third.
    ratio_exact = float(srgb_decode(np.float32(200 / 255)) / srgb_decode(np.float32(100 / 255)))
    left.text(0.97, 0.05, f"однос 200/255 : 100/255\nтачно {sr(ratio_exact)}×"
                          f"\nапроксимацијом {sr(2 ** 2.2)}×",
              fontsize=8.5, color="#333333", ha="right", va="bottom")

    save(figure, "prenosna-funkcija.png")


# -- chapter 2.2: colour spaces ------------------------------------------------


def gamut() -> None:
    """sRGB and ProPhoto RGB gamuts in the xy plane, with their white points.

    The primaries are **derived from the matrices the pipeline uses**
    (`imaging/prophoto.py`), not copied from a standard: a column of an RGB→XYZ
    matrix is that primary's tristimulus, and xy follows. Drawn this way the
    figure also double-checks the matrices, since the values have to land on the
    published ones.

    The spectral locus is deliberately absent. It needs the CIE colour-matching
    functions, which the repository does not carry, and the figure's claim — one
    space is wider and their whites differ — stands without it.
    """
    srgb_to_xyz = np.linalg.inv(_XYZ_D65_TO_SRGB)

    def chromaticities(matrix: np.ndarray) -> np.ndarray:
        columns = matrix.T
        sums = columns.sum(axis=1, keepdims=True)
        return (columns / sums)[:, :2]

    srgb_xy = chromaticities(srgb_to_xyz)
    romm_xy = chromaticities(_ROMM_TO_XYZ_D50)

    def white(matrix: np.ndarray) -> np.ndarray:
        point = matrix @ np.ones(3)
        return point[:2] / point.sum()

    figure, axes = plt.subplots(figsize=(6.6, 6.2))

    for points, colour, label, fill in (
        (romm_xy, ORANGE, "ProPhoto RGB", "#f6e6d2"),
        (srgb_xy, BLUE, "sRGB", "#dce7f2"),
    ):
        closed = np.vstack([points, points[:1]])
        axes.fill(closed[:, 0], closed[:, 1], color=fill, alpha=0.65, zorder=1)
        axes.plot(closed[:, 0], closed[:, 1], color=colour, linewidth=2.0,
                  label=label, zorder=2)

    # The two white points sit about 0.03 apart, so the labels have to be pulled
    # in opposite directions or they overlap each other and the markers.
    for point, colour, label, offset in (
        (white(_ROMM_TO_XYZ_D50), ORANGE, "D50 (ProPhoto)", (0.05, 0.05)),
        (white(srgb_to_xyz), BLUE, "D65 (sRGB)", (0.05, -0.07)),
    ):
        axes.plot(*point, marker="o", markersize=7, color=colour, zorder=3)
        target = (point[0] + offset[0], point[1] + offset[1])
        axes.annotate(f"{label}\n({sr(point[0], 4)}; {sr(point[1], 4)})",
                      xy=point, xytext=target, fontsize=8.5, color=colour,
                      arrowprops={"arrowstyle": "-", "color": colour, "linewidth": 0.8})

    names = ("црвена", "зелена", "плава")
    for point, name in zip(romm_xy, names, strict=True):
        axes.annotate(name, xy=point, xytext=(point[0] - 0.02, point[1] + 0.035),
                      fontsize=8.5, color=ORANGE, ha="center")

    axes.set_xlabel("x")
    axes.set_ylabel("y")
    axes.set_xlim(-0.05, 0.85)
    axes.set_ylim(-0.05, 0.95)
    axes.set_aspect("equal")
    axes.set_title("Два простора боја у xy равни\n(примарне изведене из матрица цеви)",
                   fontsize=11)
    axes.legend(frameon=False, fontsize=10, loc="upper right")
    style(axes)
    save(figure, "gamut.png")


# -- chapter 2.4: parametric editing ------------------------------------------

# The FiveK preset "Medium Contrast", 12.4% of edits (`edit_schema_v1.md` §4).
MEDIUM_CONTRAST = np.array(
    [[0, 0], [32, 22], [64, 56], [128, 128], [192, 196], [255, 255]], dtype=np.float64
) / 255.0
# The same mapping read backwards, which is what lowering contrast looks like.
MEDIUM_CONTRAST_INVERSE = MEDIUM_CONTRAST[:, ::-1]


def curve_shapes() -> None:
    """Four tonal shapes, all through the renderer's own interpolation.

    Two of them are not invented for the figure: the S-curve is the FiveK preset
    "Medium Contrast" exactly as the catalogue stores it, and the flattened one
    is that same mapping read backwards.
    """
    identity = np.array([[0.0, 0.0], [1.0, 1.0]])
    lifted = np.array([[0.0, 0.12], [1.0, 1.0]])

    panels = (
        (identity, "Дијагонала", "излаз је улаз — ништа се не мења"),
        (MEDIUM_CONTRAST, "S-крива", "тамно ниже, светло више: већи контраст"),
        (MEDIUM_CONTRAST_INVERSE, "Обрнута S-крива", "мањи контраст, „избледео“ изглед"),
        (lifted, "Подигнута црна", "црна не стиже до нуле — изглед филма"),
    )

    # Two rows, and the second is the one that earns its place. The FiveK preset
    # is a gentle curve: drawn against the diagonal it is nearly indistinguishable
    # from it, and from its own inverse. The deviation `y - x`, in 8-bit steps,
    # shows the shape unmistakably — and in the unit the rest of the work uses.
    figure, axes = plt.subplots(2, 4, figsize=(13.2, 6.4),
                                gridspec_kw={"height_ratios": [1.55, 1.0]})
    x = np.linspace(0.0, 1.0, 1024)

    for column, (points, title, caption) in enumerate(panels):
        curve = build_lut(points)

        upper = axes[0][column]
        upper.plot([0, 1], [0, 1], color=GREY, linewidth=1.0, linestyle=":")
        upper.plot(x, curve, color=BLUE, linewidth=2.0)
        if len(points) > 2:
            upper.plot(points[:, 0], points[:, 1], marker="o", markersize=4.5,
                       linestyle="none", color=RED)
        upper.set_xlim(0, 1)
        upper.set_ylim(0, 1)
        upper.set_aspect("equal")
        upper.set_title(title, fontsize=11)
        upper.set_xticks([0, 0.5, 1])
        upper.set_yticks([0, 0.5, 1])
        style(upper)

        lower = axes[1][column]
        deviation = (curve - x) * 255.0
        lower.axhline(0.0, color=GREY, linewidth=1.0, linestyle=":")
        lower.fill_between(x, 0.0, deviation, color=PALE, alpha=0.8)
        lower.plot(x, deviation, color=DARK, linewidth=1.6)
        lower.set_xlim(0, 1)
        lower.set_ylim(-34, 34)
        lower.set_xticks([0, 0.5, 1])
        lower.set_xlabel(caption, fontsize=8.5, labelpad=6)
        style(lower)

    axes[0][0].set_ylabel("излазна светлина")
    axes[1][0].set_ylabel("одступање од\nдијагонале (корака)")
    figure.suptitle("Тонска крива: облик одређује шта обрада ради са светлином", fontsize=12)
    save(figure, "oblici-krive.png")


def region_masks() -> None:
    """The four tone-region masks, called from `renderer/masks.py`.

    Three properties the figure has to show, all of them asserted by tests:
    the pairs sharing an end of the range sum to exactly 1, the midtones are
    protected (total weight 0.3965 at Y' = 0.5, with shadows and highlights
    exactly equal), and above white the range belongs to `whites` alone.
    """
    y = np.linspace(0.0, 1.15, 1200, dtype=np.float32)
    curves = (
        (masks.blacks(y), "blacks", DARK),
        (masks.shadows(y), "shadows", BLUE),
        (masks.highlights(y), "highlights", ORANGE),
        (masks.whites(y), "whites", RED),
    )

    figure, axes = plt.subplots(figsize=(10.0, 4.8))
    for values, label, colour in curves:
        axes.plot(y, values, color=colour, linewidth=2.0, label=label)

    total = sum(values for values, _, _ in curves)
    axes.plot(y, total, color=GREY, linewidth=1.2, linestyle="--",
              label="збир сва четири")

    axes.axvline(1.0, color="#444444", linewidth=1.0, linestyle=":")
    axes.text(1.005, 1.10, "изнад беле", fontsize=8.5, color="#444444")

    midtone = float(masks.shadows(np.array([0.5], dtype=np.float32))[0])
    axes.plot([0.5, 0.5], [0.0, float(total[np.argmin(np.abs(y - 0.5))])],
              color=GREY, linewidth=0.8, linestyle=":")
    axes.annotate(
        f"на 0,5 су shadows и highlights\nтачно једнаки: {sr(midtone, 4)}",
        xy=(0.5, midtone), xytext=(0.55, 0.52), fontsize=8.5, color="#333333",
        arrowprops={"arrowstyle": "->", "color": GREY, "linewidth": 0.8},
    )

    axes.set_xlabel("лума пиксела (Y')")
    axes.set_ylabel("удео припадности региону")
    axes.set_xlim(0, 1.15)
    axes.set_ylim(0, 1.25)
    axes.set_title("Пиксел не припада једном региону него делимично већем броју њих")
    axes.legend(frameon=False, fontsize=9, ncol=5, loc="upper center")
    style(axes)
    save(figure, "maske-regiona.png")


def lookup_table() -> None:
    """How a handful of control points becomes a table read once per pixel.

    The worked example is the one from `phase-1-concepts.md` §A1, so the figure
    and the text carry the same numbers.
    """
    points = np.array([[0.00, 0.00], [0.25, 0.15], [0.75, 0.85], [1.00, 1.00]])
    lut = build_lut(points)
    x = np.linspace(0.0, 1.0, len(lut))

    figure, axes = plt.subplots(1, 4, figsize=(13.4, 3.7))

    axes[0].plot(points[:, 0], points[:, 1], marker="o", markersize=6,
                 linestyle="none", color=RED)
    axes[0].set_title("1. Четири контролне тачке", fontsize=10.5)
    axes[0].set_xlabel("о међувредностима ништа\nније речено", fontsize=8.5, labelpad=8)

    axes[1].plot(x, lut, color=BLUE, linewidth=2.0)
    axes[1].plot(points[:, 0], points[:, 1], marker="o", markersize=5,
                 linestyle="none", color=RED)
    axes[1].set_title("2. Монотона кубна крива", fontsize=10.5)
    axes[1].set_xlabel("сада постоји одговор\nза сваки улаз", fontsize=8.5, labelpad=8)

    coarse = np.linspace(0, len(lut) - 1, 41).astype(int)
    axes[2].plot(x, lut, color=PALE, linewidth=1.4)
    axes[2].plot(x[coarse], lut[coarse], marker="o", markersize=3.2,
                 linestyle="none", color=DARK)
    axes[2].set_title("3. Узорковање у таблицу", fontsize=10.5)
    axes[2].set_xlabel("1024 вредности\n(приказано 41)", fontsize=8.5, labelpad=8)

    # Per-pixel read. Over the real table of 1024 the two neighbouring cells sit
    # 0.001 apart and nothing is visible, so the panel shows the same arithmetic
    # over a table of **nine** cells — the device `phase-1-concepts.md` §A1 uses
    # for exactly this reason, because then it can be checked by hand.
    small = 9
    coarse_lut = build_lut(points, size=small)
    coarse_x = np.linspace(0.0, 1.0, small)
    probe = 0.30
    scaled = probe * (small - 1)
    index = int(np.floor(scaled))
    fraction = scaled - index
    value = float(coarse_lut[index] * (1 - fraction) + coarse_lut[index + 1] * fraction)

    axes[3].plot(coarse_x, coarse_lut, color=PALE, linewidth=1.2, marker="o",
                 markersize=4.5, markerfacecolor=DARK, markeredgecolor=DARK)
    axes[3].plot(coarse_x[index : index + 2], coarse_lut[index : index + 2],
                 color=BLUE, linewidth=2.2)
    axes[3].plot([probe], [value], marker="X", markersize=10, color=RED, zorder=5)
    axes[3].annotate(
        f"улаз {sr(probe)}\nизлаз {sr(value, 3)}",
        xy=(probe, value), xytext=(0.42, 0.13), fontsize=8.5, color=RED,
        arrowprops={"arrowstyle": "->", "color": RED, "linewidth": 0.9},
    )
    axes[3].text(0.04, 0.88,
                 f"ћелија {index} и {index + 1},\nудео {sr(fraction, 1)}",
                 fontsize=8.5, color="#333333")
    axes[3].set_title("4. Читање по пикселу", fontsize=10.5)
    axes[3].set_xlabel("над таблицом од 9 ћелија,\nда се рачун види",
                       fontsize=8.5, labelpad=8)

    for panel in axes:
        panel.set_xlim(0, 1)
        panel.set_ylim(0, 1)
        panel.set_aspect("equal")
        panel.set_xticks([0, 0.5, 1])
        panel.set_yticks([0, 0.5, 1])
        style(panel)
    axes[0].set_ylabel("излазна светлина")

    figure.suptitle(
        "Тежак део се изврши 1024 пута укупно, а не по пикселу", fontsize=11.5
    )
    save(figure, "tablica-vrednosti.png")


# -- chapter 2.6: diversity ----------------------------------------------------


def mmr() -> None:
    """The worked MMR example from `phase-3-concepts.md` §B61.

    The point of the figure is the swap: ranking by quality alone takes the
    candidate that adds nothing, and MMR drops it precisely because it adds
    nothing.
    """
    names = ["A", "B", "C", "D", "E"]
    relevance = np.array([0.95, 0.93, 0.88, 0.70, 0.60])
    similarity = np.array([np.nan, 0.97, 0.40, 0.20, 0.10])
    lam = 0.5
    scores = lam * relevance - (1 - lam) * similarity

    figure, (left, right) = plt.subplots(1, 2, figsize=(11.0, 4.3))
    positions = np.arange(len(names))

    colours = [DARK if index < 3 else PALE for index in range(len(names))]
    left.bar(positions, relevance, width=0.6, color=colours)
    for position, value in zip(positions, relevance, strict=True):
        left.text(position, value + 0.015, sr(value), ha="center", fontsize=9)
    left.set_ylim(0, 1.12)
    left.set_ylabel("релевантност (сличност сцене)")
    left.set_xlabel("изабрана су прва три,\nа други је готово исти као први")
    left.set_title("Обичан поредак по квалитету", fontsize=11)
    # After `style`, which sets a numeric formatter that would wipe these labels.
    style(left)
    left.set_xticks(positions, names)

    right.bar(positions[:1], [relevance[0]], width=0.6, color=DARK)
    right.text(0, relevance[0] + 0.015, "изабран", ha="center", fontsize=8.5, color=DARK)
    picked = [False, False, False, True, True]
    right.bar(positions[1:], scores[1:], width=0.6,
              color=[DARK if flag else PALE for flag in picked[1:]])
    for position, value in zip(positions[1:], scores[1:], strict=True):
        offset = 0.015 if value >= 0 else -0.055
        right.text(position, value + offset, sr(value), ha="center", fontsize=9)
    right.axhline(0.0, color=GREY, linewidth=1.0)
    right.set_ylim(-0.12, 1.12)
    right.set_ylabel("оцена у другом кораку (λ = 0,5)")
    right.set_xlabel("други по квалитету испада;\nу другом кораку побеђује један од двоје најдаљих")
    right.set_title("MMR: квалитет минус сличност са изабраним", fontsize=11)
    style(right)
    right.set_xticks(positions, names)

    right.annotate("сличност са првим: 0,97", xy=(1, scores[1]), xytext=(1.15, 0.42),
                   fontsize=8.5, color=RED,
                   arrowprops={"arrowstyle": "->", "color": RED, "linewidth": 0.9})

    figure.suptitle(
        "Кандидат који не доноси ништа ново испада, ма колико био добар", fontsize=11.5
    )
    save(figure, "mmr.png")


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    print(f"пишем у {FIGURES}")
    transfer_function()
    gamut()
    curve_shapes()
    region_masks()
    lookup_table()
    mmr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
