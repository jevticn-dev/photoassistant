"""Figures for the phase 3 report, drawn from the JSON the evaluation already wrote.

    uv run --project ml python -m pipeline.figures

Reads ``pipeline/reports/evaluation/*.json`` and writes PNGs into
``docs/reports/figures/phase-3/``. It computes nothing: every number on every axis
comes from a file produced by a measured run, so a figure can never disagree with
the table beside it.

Four pictures, one per question the phase asks. By default each arm figure shows
the nine arms in ``SELECTED``; ``--all`` redraws them with every arm, written
beside the first under a ``-all`` suffix.

``hit-rate-curve``
    the share of photographs where some suggestion landed near an expert, against
    where the bar is put. Drawn whole because a single threshold is a lever — if
    two arms cross, that is worth seeing rather than hiding behind one point
    (§B56).

``diversity``
    how varied each arm's three suggestions are, as a fraction of how varied five
    experts are on the same photograph. 1,0 is the target, and both the rendered
    and the fingerprint figure are shown, since the distance between them is the
    risk ADR-23 exists to size.

``closeness``
    the distance from the best suggestion to the nearest expert, with the ceiling
    and the floors marked. A number here means nothing on its own: 4,3 is good or
    bad depending entirely on where 0,8 and 5,2 sit.

``index-and-latency``
    what the index costs against exact search, and where one request's time goes.
    Drawn from ``index.json`` and ``latency.json`` rather than the arm summaries,
    and together because they answer one question: search is not what a request
    spends its time on.

**matplotlib is a dev dependency.** Nothing in the library or the service imports
this module, so neither the pipeline's install set nor the container image grows.
"""

import argparse
import json
import os
from pathlib import Path

import matplotlib

# No window manager on a CI box, and none wanted here either: this writes files.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from pipeline.environment import REPOSITORY_ROOT  # noqa: E402

RESULTS = Path(
    os.environ.get("EVALUATION_DIR") or REPOSITORY_ROOT / "pipeline/reports/evaluation"
)
FIGURES = Path(
    os.environ.get("FIGURES_DIR") or REPOSITORY_ROOT / "docs/reports/figures/phase-3"
)

# Reading order rather than alphabetical: the ceiling first, then the baselines,
# then what the phase is actually proposing. A reader compares against the bounds.
ORDER = [
    "oracle",
    "average",
    "random",
    "top",
    "top-per-scene",
    "kmeans",
    "mmr-0.3",
    "mmr-0.5",
    "mmr-0.7",
    "mmr-0.5-k20",
    "mmr-0.5-k100",
    "mmr-0.5+render6",
]

HIGHLIGHT = {"oracle": "#111111", "average": "#999999", "random": "#bbbbbb"}

# What a **reader** can take in. The phase ran 23 arms; drawing all of them on one
# pair of axes produces a picture in which no line can be followed and two arms
# share a colour. The report shows these, and `--all` redraws everything for the
# appendix, where the question is "was it run" rather than "what does it say".
#
# Chosen to span the argument: both bounds, both baselines, the shipped
# configuration, and one representative of each family that lost.
SELECTED = [
    "oracle",
    "average",
    "random",
    "top",
    "top-per-scene",
    "top-per-scene-bestfit",
    "kmeans",
    "mmr-0.5",
    "mmr-0.5+render6",
]

# Fingerprint diversity is a distance **inside a fingerprint space**, so it can
# only be compared between arms that share one. Every `fp-*`, `kmeans-fp-*` and
# `probe-*` arm changes what the fingerprint is made of, which moves the scale
# along with it — the same mistake that produced the 0,23 artefact in task 11
# (§B72). Those arms keep their rendered bar, which is measured in ΔE on screen
# and therefore comparable everywhere, and lose the fingerprint one.
def same_fingerprint_space(name: str) -> bool:
    return not (name.startswith(("fp-", "probe-")) or "-fp-" in name)


def load(directory: Path) -> dict[str, dict]:
    """Every arm's summary, in reading order, ignoring the control runs."""
    summaries = {}
    for path in sorted(directory.glob("*.json")):
        if path.stem.endswith("-no-exclusion"):
            continue
        summaries[path.stem] = json.loads(path.read_text(encoding="utf-8"))

    ordered = {name: summaries[name] for name in ORDER if name in summaries}
    ordered.update({name: value for name, value in summaries.items() if name not in ordered})
    return ordered


def sr(value: float, decimals: int = 2) -> str:
    """A number as Serbian writes it — the figures are labelled in Serbian."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _style(axes) -> None:
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.grid(alpha=0.25, linewidth=0.6)
    axes.set_axisbelow(True)


def hit_rate_curve(summaries: dict[str, dict], path: Path) -> None:
    figure, axes = plt.subplots(figsize=(9, 5.5))

    palette = plt.get_cmap("tab10")
    index = 0
    for name, summary in summaries.items():
        curve = summary.get("hit_rate_curve") or []
        if not curve:
            continue
        colour = HIGHLIGHT.get(name)
        if colour is None:
            colour = palette(index % 10)
            index += 1
        axes.plot(
            [point["threshold"] for point in curve],
            [point["rate"] for point in curve],
            label=name,
            linewidth=2.2 if name in HIGHLIGHT else 1.6,
            linestyle="--" if name in {"average", "random"} else "-",
            color=colour,
            alpha=1.0,
        )

    axes.axvline(1.0, color="#cc4444", linewidth=1.0, linestyle=":")
    axes.text(1.15, 0.02, "granica primetnosti", fontsize=8, color="#cc4444")

    axes.set_xlabel("prag ΔE (koliko blizu ekspertu se računa kao pogodak)")
    axes.set_ylabel("udeo fotografija sa bar jednim pogotkom")
    axes.set_title("Kriva pogotka — cela, jer jedan prag bira pobednika")
    axes.set_ylim(0, 1.02)
    _style(axes)
    axes.legend(fontsize=8, ncols=1, frameon=False, loc="lower right")
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def diversity(summaries: dict[str, dict], path: Path) -> None:
    names = [name for name, summary in summaries.items() if summary.get("diversity_ratio")]
    rendered = [summaries[name]["diversity_ratio"].get("median") for name in names]
    fingerprint = [
        summaries[name].get("fingerprint_ratio", {}).get("median")
        if same_fingerprint_space(name)
        else None
        for name in names
    ]

    figure, axes = plt.subplots(figsize=(9, 5.5))
    positions = range(len(names))
    axes.bar(
        [position - 0.2 for position in positions],
        rendered,
        width=0.4,
        label="na ekranu (renderovano)",
        color="#3b6ea5",
    )
    axes.bar(
        [position + 0.2 for position in positions],
        [value if value is not None else 0.0 for value in fingerprint],
        width=0.4,
        label="po otiscima",
        color="#b8c9dd",
    )
    axes.axhline(1.0, color="#cc4444", linewidth=1.2)
    # Above the line and hard left, where no bar reaches: written at the right edge
    # it ran straight through the bars of every arm near the human scale.
    axes.text(
        -0.4,
        1.06,
        "1,0 = koliko se razilazi pet eksperata",
        fontsize=8,
        color="#cc4444",
        ha="left",
    )

    axes.set_xticks(list(positions), names, rotation=35, ha="right", fontsize=8)
    axes.set_ylabel("raznovrsnost, kao udeo ljudskog neslaganja")
    axes.set_title("Raznovrsnost predloga naspram ljudske skale")
    axes.set_ylim(0, max(1.35, max(rendered) * 1.15))
    _style(axes)
    axes.legend(fontsize=8, frameon=False)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def closeness(summaries: dict[str, dict], path: Path) -> None:
    names = [name for name, summary in summaries.items() if summary.get("closeness_delta_e")]
    medians = [summaries[name]["closeness_delta_e"]["median"] for name in names]
    low = [summaries[name]["closeness_delta_e"]["p10"] for name in names]
    high = [summaries[name]["closeness_delta_e"]["p90"] for name in names]

    figure, axes = plt.subplots(figsize=(9, 5.5))
    positions = list(range(len(names)))
    axes.errorbar(
        medians,
        positions,
        xerr=[
            [median - lower for median, lower in zip(medians, low, strict=True)],
            [upper - median for median, upper in zip(medians, high, strict=True)],
        ],
        fmt="o",
        color="#3b6ea5",
        ecolor="#b8c9dd",
        elinewidth=3,
        capsize=0,
        markersize=6,
    )

    if "oracle" in summaries:
        ceiling = summaries["oracle"]["closeness_delta_e"]["median"]
        axes.axvline(ceiling, color="#111111", linewidth=1.2, linestyle="--")
        axes.text(ceiling + 0.1, len(names) - 0.6, "plafon", fontsize=8)
    if "average" in summaries:
        floor = summaries["average"]["closeness_delta_e"]["median"]
        axes.axvline(floor, color="#999999", linewidth=1.2, linestyle="--")
        axes.text(floor + 0.1, len(names) - 0.6, "pod", fontsize=8, color="#666666")

    axes.set_yticks(positions, names, fontsize=8)
    axes.invert_yaxis()
    axes.set_xlabel("ΔE od najboljeg predloga do najbližeg eksperta (medijana, p10–p90)")
    axes.set_title("Blizina ekspertu — čita se između poda i plafona")
    _style(axes)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def index_and_latency(path: Path) -> bool:
    """What the index costs and what the user waits — the two service numbers.

    Both come from their own measured runs (`measure_index.py`,
    `measure_latency.py`); nothing here is recomputed. They share a figure because
    they answer one question together: the search is not what the request spends
    its time on.
    """
    index_report = REPOSITORY_ROOT / "pipeline/reports/index.json"
    latency_report = REPOSITORY_ROOT / "pipeline/reports/latency.json"
    if not (index_report.exists() and latency_report.exists()):
        return False

    index = json.loads(index_report.read_text(encoding="utf-8"))
    latency = json.loads(latency_report.read_text(encoding="utf-8"))

    figure, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4))

    # -- left: the three query shapes the system really has ---------------------
    shapes = [
        ("približno\n(indeks)", "approximate", "#3b6ea5"),
        ("tačno\n(bez indeksa)", "exact", "#7f9fc4"),
        ("filtrirano\n(ispit)", "filtered", "#b8c9dd"),
    ]
    values = [index["latency"][key]["median_ms"] for _, key, _ in shapes]
    left.bar(
        [label for label, _, _ in shapes],
        values,
        color=[colour for _, _, colour in shapes],
        width=0.6,
    )
    for position, value in enumerate(values):
        left.text(position, value * 1.05, f"{sr(value)} ms", ha="center", fontsize=9)
    left.set_yscale("log")
    left.set_ylim(1, max(values) * 3)
    left.set_ylabel("medijana po upitu (ms, logaritamska osa)")
    left.set_title("Oblik upita odlučuje cenu", fontsize=11)
    recall = index["recall"]
    perfect = sr(recall["perfect_share"] * 100, 1)
    left.text(
        0.5,
        -0.26,
        f"recall {sr(recall['mean'], 4)}, savršen na {perfect}% upita\n"
        f"tri predloga se razlikuju na {index['suggestions_differing']} od {index['queries']}",
        transform=left.transAxes,
        ha="center",
        fontsize=8,
        color="#555555",
    )
    _style(left)

    # -- right: where a request's time goes -------------------------------------
    stages = [
        ("dekodiranje", "decode", "#b8c9dd"),
        ("CLIP", "embed", "#7f9fc4"),
        ("pretraga", "search", "#3b6ea5"),
        ("tri sličice", "render", "#1f4e79"),
    ]
    start = 0.0
    total = sum(latency["stages"][key]["median_ms"] for _, key, _ in stages)
    for label, key, colour in stages:
        width = latency["stages"][key]["median_ms"]
        right.barh([0], [width], left=[start], color=colour, height=0.45, label=label)
        if width / total > 0.08:
            right.text(
                start + width / 2,
                0,
                f"{width:.0f}",
                ha="center",
                va="center",
                fontsize=9,
                color="white",
            )
        start += width

    end_to_end = latency["end_to_end"]
    right.axvline(end_to_end["p95_ms"], color="#cc4444", linewidth=1.2, linestyle="--")
    right.text(
        end_to_end["p95_ms"] + 4,
        0.33,
        f"p95 {end_to_end['p95_ms']:.0f} ms\n(ceo zahtev)",
        fontsize=8,
        color="#cc4444",
    )
    right.set_yticks([])
    right.set_ylim(-0.5, 0.6)
    right.set_xlabel("milisekunde")
    right.set_title("Gde odlazi vreme jednog zahteva", fontsize=11)
    right.text(
        0.5,
        -0.26,
        f"budžet {latency['budget_p95_seconds'] * 1000:.0f} ms na p95, izmereno "
        f"{end_to_end['p95_ms']:.0f} ms\ndelovi mereni zasebno: zbir {total:.0f} ms, "
        f"medijana celog zahteva {end_to_end['median_ms']:.0f} ms",
        transform=right.transAxes,
        ha="center",
        fontsize=8,
        color="#555555",
    )
    right.legend(fontsize=8, frameon=False, ncols=4, loc="upper center")
    _style(right)

    # tight_layout does not know about text placed below the axes in axes
    # coordinates, so the captions have to be given their own room afterwards.
    figure.tight_layout()
    figure.subplots_adjust(bottom=0.26)
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw the phase 3 figures.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="draw every arm instead of the nine the report reads",
    )
    arguments = parser.parse_args()

    summaries = load(RESULTS)
    if not summaries:
        print(f"no evaluation results in {RESULTS}")
        return 1

    if not arguments.all:
        chosen = {name: summaries[name] for name in SELECTED if name in summaries}
        missing = [name for name in SELECTED if name not in summaries]
        if missing:
            print(f"not measured, so not drawn: {', '.join(missing)}")
        summaries = chosen

    suffix = "-all" if arguments.all else ""
    FIGURES.mkdir(parents=True, exist_ok=True)
    hit_rate_curve(summaries, FIGURES / f"hit-rate-curve{suffix}.png")
    diversity(summaries, FIGURES / f"diversity{suffix}.png")
    closeness(summaries, FIGURES / f"closeness{suffix}.png")
    if not index_and_latency(FIGURES / "index-and-latency.png"):
        print("index.json or latency.json missing — that figure is not drawn")

    print(f"arms {len(summaries)}: {', '.join(summaries)}")
    print(f"written to {FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
