"""Figures for the thesis, labelled in Serbian Cyrillic.

    uv run --project ml --extra service python -m sandbox.thesis_figures

Separate from `pipeline/figures.py` on purpose, and the duplication is deliberate
rather than overlooked. That module is a working tool: it is labelled in Latin,
it draws whatever arms happen to be measured, and it is part of the delivered
repository. This one serves one document, is labelled in the script that document
is written in, and picks the subset a reader of a thesis can take in.

Sandbox, because CLAUDE.md reserves this directory for exactly that — work that
is not part of the delivery.

**Output is not committed.** Several of these contain FiveK imagery, whose licence
is research-only while the repository is public (`.claude/rules/pipeline.md`).
docs/thesis/ is in .git/info/exclude for that reason.
"""

import json
import os
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from photoassistant.renderer import delta_e, quantise, render  # noqa: E402
from photoassistant.schema import EditRecipe  # noqa: E402
from photoassistant.storage import DatabaseConfig, connect  # noqa: E402

from pipeline.contact_sheets import heat_map  # noqa: E402
from pipeline.environment import REPOSITORY_ROOT, load  # noqa: E402
from pipeline.fit_all import load_image, store  # noqa: E402

FIGURES = Path(os.environ.get("THESIS_FIGURES") or REPOSITORY_ROOT / "docs/thesis/figures")
REPORTS = REPOSITORY_ROOT / "pipeline/reports"
BLUE, PALE, DARK, RED = "#3b6ea5", "#b8c9dd", "#1f4e79", "#cc4444"


def sr(value: float, decimals: int = 2) -> str:
    """Serbian decimal comma."""
    return f"{value:.{decimals}f}".replace(".", ",")


def style(axes) -> None:
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.grid(alpha=0.25, linewidth=0.6)
    axes.set_axisbelow(True)


def save(figure, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURES / name, dpi=200, bbox_inches="tight")
    plt.close(figure)
    print(f"  {name}")


# -- figures over images ------------------------------------------------------


def comparison(connection, kind: str, name: str) -> None:
    """Before, our reconstruction, the expert, and where the two differ.

    The figure the fitting chapter needs: a mean ΔE cannot distinguish "slightly
    wrong everywhere" from "badly wrong in one respect", and the heat map can.
    """
    order = "ASC" if kind == "best" else "DESC"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT p.source_reference, e.expert, e.edit, e.fit_error
              FROM examples e JOIN photos p ON p.id = e.photo_id
             WHERE e.fit_error IS NOT NULL AND NOT e.excluded_from_fitting
             ORDER BY e.fit_error {order}
             LIMIT 1 OFFSET 1
            """
        )
        reference, expert, edit, error = cursor.fetchone()

    bucket = store().derivatives
    before = load_image(bucket, f"fivek/{reference}/pre512.png")
    after = load_image(bucket, f"fivek/{reference}/after512-{expert}.png")
    ours = render(before, EditRecipe.model_validate(edit))

    panels = [
        ("полазна фотографија", quantise(before)),
        ("наша реконструкција", quantise(ours)),
        (f"обрада експерта {expert.upper()}", quantise(after)),
        ("разлика, 0 до 10 ΔE", heat_map(delta_e(ours, after))),
    ]

    figure, axes = plt.subplots(1, 4, figsize=(14, 3.4))
    for axis, (label, panel) in zip(axes, panels, strict=True):
        axis.imshow(panel)
        axis.set_title(label, fontsize=9)
        axis.set_xticks([])
        axis.set_yticks([])
        for side in axis.spines.values():
            side.set_visible(False)
    figure.suptitle(
        f"{reference} · средња грешка реконструкције {sr(error)} ΔE", fontsize=10, y=1.02
    )
    save(figure, name)


def five_experts(connection) -> None:
    """One photograph with all five expert edits and the neutral starting point.

    The figure chapter 3 needs: the dataset's whole claim is that there are five
    answers to the same question, and a sentence does not carry that.

    The photograph is **not** the one where the experts disagree most, which
    would be picking the example that flatters the argument. It is the one whose
    disagreement sits closest to the median of the held-out set, so the reader
    sees a typical case and the caption can say so.
    """
    report = json.loads((REPORTS / "expert_agreement.json").read_text("utf-8"))
    entries = report["per_photograph"]
    values = np.array([entry["human_mean"] for entry in entries.values()])
    median = float(np.median(values))
    reference = min(entries, key=lambda key: abs(entries[key]["human_mean"] - median))
    disagreement = entries[reference]["human_mean"]

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.pre512_key, e.expert, e.after_key
              FROM examples e JOIN photos p ON p.id = e.photo_id
             WHERE p.source_reference = %s AND e.after_key IS NOT NULL
             ORDER BY e.expert
            """,
            (reference,),
        )
        rows = cursor.fetchall()

    bucket = store().derivatives
    panels = [("полазна (неутрална)", load_image(bucket, rows[0][0]))]
    panels += [
        (f"експерт {expert.upper()}", load_image(bucket, key)) for _, expert, key in rows
    ]

    figure, axes = plt.subplots(2, 3, figsize=(11.4, 6.2))
    for panel, (label, pixels) in zip(axes.ravel(), panels, strict=True):
        panel.imshow(np.clip(pixels, 0.0, 1.0))
        panel.set_title(label, fontsize=10.5)
        panel.set_xticks([])
        panel.set_yticks([])
        for spine in panel.spines.values():
            spine.set_edgecolor("#cccccc")

    figure.suptitle(
        "Пет експерата, једна фотографија — пет различитих обрада\n"
        f"(неслагање {sr(disagreement)} ΔE, готово тачно медијана издвојеног скупа)",
        fontsize=11.5,
    )
    figure.tight_layout()
    save(figure, "pet-eksperata.png")


# -- figures over measured data -----------------------------------------------


def fit_error(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT fit_error FROM examples "
            "WHERE fit_error IS NOT NULL AND NOT excluded_from_fitting"
        )
        values = np.array([row[0] for row in cursor.fetchall()], dtype=np.float64)

    figure, axes = plt.subplots(figsize=(9, 4.6))
    axes.hist(values, bins=120, range=(0, 8), color=BLUE, edgecolor="none")
    median = float(np.median(values))
    # Both markers land inside the histogram's tallest region, so inline text
    # would sit on top of the bars. A legend keeps them readable.
    axes.axvline(median, color=RED, linewidth=1.4, linestyle="--",
                 label=f"медијана {sr(median, 4)} ΔE")
    axes.axvline(1.0, color="#444444", linewidth=1.2, linestyle=":",
                 label="граница приметности (1 ΔE)")
    axes.set_xlabel("грешка реконструкције (ΔE)")
    axes.set_ylabel("број обрада")
    count = f"{len(values):,}".replace(",", ".")
    axes.set_title(f"Колико верно шема измене репродукује {count} експертских обрада")
    axes.legend(frameon=False, fontsize=9)
    style(axes)
    save(figure, "greska-fitovanja.png")


def bandwidth() -> None:
    report = json.loads((REPOSITORY_ROOT / "pipeline/bandwidth_report.json").read_text("utf-8"))
    # The last level repeats the first as a control; it is not a measurement point.
    levels = report["levels"][:-1]
    concurrency = [entry["concurrency"] for entry in levels]
    total = [entry["megabytes_per_second"] for entry in levels]
    per_connection = [entry["per_file_mbps_median"] for entry in levels]

    figure, axes = plt.subplots(figsize=(8, 4.6))
    positions = range(len(levels))
    axes.bar(positions, total, width=0.55, color=BLUE, label="укупна пропусност")
    for position, value in zip(positions, total, strict=True):
        axes.text(position, value + 1, f"{sr(value)}", ha="center", fontsize=9)

    twin = axes.twinx()
    twin.plot(positions, per_connection, color=RED, marker="o", linewidth=1.6,
              label="по вези")
    twin.set_ylabel("по вези (MB/s)", color=RED)
    twin.set_ylim(0, max(per_connection) * 1.6)
    twin.spines["top"].set_visible(False)

    axes.set_xticks(list(positions), [str(value) for value in concurrency])
    axes.set_xlabel("број паралелних веза")
    axes.set_ylabel("укупно (MB/s)")
    axes.set_ylim(0, max(total) * 1.25)
    axes.set_title("Пропусност расте, а по вези опада — отуд радна тачка на шест")
    style(axes)
    figure.legend(loc="upper left", bbox_to_anchor=(0.13, 0.88), frameon=False, fontsize=9)
    save(figure, "propusnost.png")


def expert_agreement() -> None:
    report = json.loads((REPORTS / "expert_agreement.json").read_text("utf-8"))
    values = np.array(
        [entry["human_mean"] for entry in report["per_photograph"].values()], dtype=np.float64
    )

    figure, axes = plt.subplots(figsize=(9, 4.6))
    axes.hist(values, bins=40, color=PALE, edgecolor=BLUE, linewidth=0.6)
    median = float(np.median(values))
    axes.axvline(median, color=RED, linewidth=1.4, linestyle="--")
    axes.text(median + 0.25, axes.get_ylim()[1] * 0.9, f"медијана {sr(median)} ΔE",
              color=RED, fontsize=9)
    axes.set_xlabel("просечно међусобно растојање обрада пет експерата (ΔE)")
    axes.set_ylabel("број фотографија")
    axes.set_title("Колико се пет експерата разилази на истој фотографији")
    style(axes)
    save(figure, "neslaganje-eksperata.png")


# -- evaluation figures, in Cyrillic ------------------------------------------

SELECTED = [
    ("oracle", "горња граница", "#111111"),
    ("average", "доња граница", "#999999"),
    ("random", "насумично", "#bbbbbb"),
    ("top", "три најближа едита", None),
    ("top-per-scene", "по један из три сцене", None),
    ("top-per-scene-bestfit", "по један из три сцене + најбољи фит", None),
    ("kmeans", "груписање (k-means)", None),
    ("mmr-0.5", "MMR, λ = 0,5", None),
    ("mmr-0.5+render6", "двостепени избор", None),
]


def summaries() -> dict[str, dict]:
    out = {}
    for name, _, _ in SELECTED:
        path = REPORTS / "evaluation" / f"{name}.json"
        if path.is_file():
            out[name] = json.loads(path.read_text("utf-8"))
    return out


def hit_rate_curve(data: dict[str, dict]) -> None:
    figure, axes = plt.subplots(figsize=(9, 5.4))
    palette = plt.get_cmap("tab10")
    index = 0
    for name, label, colour in SELECTED:
        curve = data.get(name, {}).get("hit_rate_curve") or []
        if not curve:
            continue
        if colour is None:
            colour = palette(index % 10)
            index += 1
        axes.plot(
            [point["threshold"] for point in curve],
            [point["rate"] for point in curve],
            label=label,
            linewidth=2.2 if name in {"oracle", "average", "random"} else 1.6,
            linestyle="--" if name in {"average", "random"} else "-",
            color=colour,
        )
    axes.axvline(1.0, color=RED, linewidth=1.0, linestyle=":")
    axes.text(1.15, 0.02, "граница приметности", fontsize=8, color=RED)
    axes.set_xlabel("праг ΔE — колико близу експерту се рачуна као погодак")
    axes.set_ylabel("удео фотографија са бар једним поготком")
    axes.set_title("Крива поготка, цела — јер један праг бира победника")
    axes.set_ylim(0, 1.02)
    style(axes)
    axes.legend(fontsize=8, frameon=False, loc="lower right")
    save(figure, "kriva-pogotka.png")


def closeness(data: dict[str, dict]) -> None:
    rows = [(label, data[name]["closeness_delta_e"])
            for name, label, _ in SELECTED if name in data]
    medians = [row[1]["median"] for row in rows]
    low = [row[1]["p10"] for row in rows]
    high = [row[1]["p90"] for row in rows]

    figure, axes = plt.subplots(figsize=(9, 5.0))
    positions = list(range(len(rows)))
    axes.errorbar(
        medians, positions,
        xerr=[[m - lo for m, lo in zip(medians, low, strict=True)],
              [hi - m for m, hi in zip(medians, high, strict=True)]],
        fmt="o", color=BLUE, ecolor=PALE, elinewidth=3, capsize=0, markersize=6,
    )
    # The two bounds are already named on the y axis, so the lines carry no text
    # of their own; they are there to be read across, not labelled twice.
    if "oracle" in data:
        axes.axvline(data["oracle"]["closeness_delta_e"]["median"], color="#111111",
                     linewidth=1.2, linestyle="--")
    if "average" in data:
        axes.axvline(data["average"]["closeness_delta_e"]["median"], color="#999999",
                     linewidth=1.2, linestyle="--")

    axes.set_yticks(positions, [row[0] for row in rows], fontsize=9)
    axes.invert_yaxis()
    axes.set_xlabel("ΔE од најбољег предлога до најближег експерта (медијана, p10–p90)")
    axes.set_title("Близина експерту — чита се између две границе")
    style(axes)
    save(figure, "blizina.png")


def diversity(data: dict[str, dict]) -> None:
    rows = [(label, data[name]) for name, label, _ in SELECTED
            if name in data and data[name].get("diversity_ratio")]
    rendered = [row[1]["diversity_ratio"]["median"] for row in rows]
    fingerprint = [row[1].get("fingerprint_ratio", {}).get("median") or 0.0 for row in rows]

    figure, axes = plt.subplots(figsize=(9, 5.0))
    positions = range(len(rows))
    axes.bar([p - 0.2 for p in positions], rendered, width=0.4, color=BLUE,
             label="на екрану (рендеровано)")
    axes.bar([p + 0.2 for p in positions], fingerprint, width=0.4, color=PALE,
             label="по отисцима")
    axes.axhline(1.0, color=RED, linewidth=1.2)
    axes.set_xticks(list(positions), [row[0] for row in rows], rotation=30, ha="right",
                    fontsize=8)
    axes.set_ylabel("разноврсност, као удео људског неслагања")
    axes.set_title("Разноврсност предлога наспрам људске скале")
    ceiling = max(1.35, max(rendered) * 1.25)
    axes.set_ylim(0, ceiling)
    # Above every bar rather than beside the line: at y = 1 the text crossed the
    # bars of each arm that sits near the human scale, which is most of them.
    axes.text(-0.45, ceiling * 0.95, "1,0 = колико се разилази пет експерата",
              fontsize=8, color=RED, va="top")
    style(axes)
    axes.legend(fontsize=8, frameon=False)
    save(figure, "raznovrsnost.png")


def index_and_latency() -> None:
    index = json.loads((REPORTS / "index.json").read_text("utf-8"))
    latency = json.loads((REPORTS / "latency.json").read_text("utf-8"))

    figure, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4))

    shapes = [("приближно\n(индекс)", "approximate", BLUE),
              ("тачно\n(без индекса)", "exact", "#7f9fc4"),
              ("филтрирано\n(испит)", "filtered", PALE)]
    values = [index["latency"][key]["median_ms"] for _, key, _ in shapes]
    left.bar([label for label, _, _ in shapes], values,
             color=[colour for _, _, colour in shapes], width=0.6)
    for position, value in enumerate(values):
        left.text(position, value * 1.05, f"{sr(value)} ms", ha="center", fontsize=9)
    left.set_yscale("log")
    left.set_ylim(1, max(values) * 3)
    left.set_ylabel("медијана по упиту (ms, логаритамска оса)")
    left.set_title("Облик упита одлучује цену", fontsize=11)
    recall = index["recall"]
    left.text(0.5, -0.26,
              f"recall {sr(recall['mean'], 4)}, савршен на "
              f"{sr(recall['perfect_share'] * 100, 1)}% упита\nтри предлога се разликују на "
              f"{index['suggestions_differing']} од {index['queries']}",
              transform=left.transAxes, ha="center", fontsize=8, color="#555555")
    style(left)

    stages = [("декодирање", "decode", PALE), ("CLIP", "embed", "#7f9fc4"),
              ("претрага", "search", BLUE), ("три сличице", "render", DARK)]
    start = 0.0
    total = sum(latency["stages"][key]["median_ms"] for _, key, _ in stages)
    for label, key, colour in stages:
        width = latency["stages"][key]["median_ms"]
        right.barh([0], [width], left=[start], color=colour, height=0.45, label=label)
        if width / total > 0.08:
            right.text(start + width / 2, 0, f"{width:.0f}", ha="center", va="center",
                       fontsize=9, color="white")
        start += width

    end_to_end = latency["end_to_end"]
    right.axvline(end_to_end["p95_ms"], color=RED, linewidth=1.2, linestyle="--")
    right.text(end_to_end["p95_ms"] + 4, 0.33,
               f"95. перцентил\n{end_to_end['p95_ms']:.0f} ms", fontsize=8, color=RED)
    right.set_yticks([])
    right.set_ylim(-0.5, 0.6)
    right.set_xlabel("милисекунде")
    right.set_title("Где одлази време једног захтева", fontsize=11)
    right.text(0.5, -0.26,
               f"медијана целог захтева {end_to_end['median_ms']:.0f} ms\n"
               f"делови мерени засебно, па им збир ({total:.0f} ms) није једнак медијани",
               transform=right.transAxes, ha="center", fontsize=8, color="#555555")
    right.legend(fontsize=8, frameon=False, ncols=4, loc="upper center")
    style(right)

    figure.tight_layout()
    figure.subplots_adjust(bottom=0.26)
    save(figure, "indeks-i-latencija.png")


def main() -> int:
    load()
    FIGURES.mkdir(parents=True, exist_ok=True)
    print(f"пишем у {FIGURES}")

    with connect(DatabaseConfig.from_environment()) as connection:
        five_experts(connection)
        comparison(connection, "best", "poredjenje-najbolji.png")
        comparison(connection, "worst", "poredjenje-najgori.png")
        fit_error(connection)

    bandwidth()
    expert_agreement()

    data = summaries()
    hit_rate_curve(data)
    closeness(data)
    diversity(data)
    index_and_latency()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
