"""Figures for the phase 3 report, drawn from the JSON the evaluation already wrote.

    uv run --project ml python -m pipeline.figures

Reads ``pipeline/reports/evaluation/*.json`` and writes PNGs into
``docs/reports/figures/phase-3/``. It computes nothing: every number on every axis
comes from a file produced by a measured run, so a figure can never disagree with
the table beside it.

Three pictures, one per question the phase asks:

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


def _style(axes) -> None:
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.grid(alpha=0.25, linewidth=0.6)
    axes.set_axisbelow(True)


def hit_rate_curve(summaries: dict[str, dict], path: Path) -> None:
    figure, axes = plt.subplots(figsize=(9, 5.5))

    for name, summary in summaries.items():
        curve = summary.get("hit_rate_curve") or []
        if not curve:
            continue
        colour = HIGHLIGHT.get(name)
        axes.plot(
            [point["threshold"] for point in curve],
            [point["rate"] for point in curve],
            label=name,
            linewidth=2.2 if colour else 1.4,
            linestyle="--" if name in {"average", "random"} else "-",
            color=colour,
            alpha=1.0 if colour else 0.9,
        )

    thresholds = [
        summary["closeness_delta_e"].get("median")
        for summary in summaries.values()
        if summary.get("closeness_delta_e")
    ]
    if thresholds:
        axes.axvline(1.0, color="#cc4444", linewidth=1.0, linestyle=":")
        axes.text(1.15, 0.02, "granica primetnosti", fontsize=8, color="#cc4444")

    axes.set_xlabel("prag ΔE (koliko blizu ekspertu se računa kao pogodak)")
    axes.set_ylabel("udeo fotografija sa bar jednim pogotkom")
    axes.set_title("Kriva pogotka — cela, jer jedan prag bira pobednika")
    axes.set_ylim(0, 1.02)
    _style(axes)
    axes.legend(fontsize=8, ncols=2, frameon=False)
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def diversity(summaries: dict[str, dict], path: Path) -> None:
    names = [name for name, summary in summaries.items() if summary.get("diversity_ratio")]
    rendered = [summaries[name]["diversity_ratio"].get("median") for name in names]
    fingerprint = [
        summaries[name].get("fingerprint_ratio", {}).get("median") for name in names
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
    axes.text(len(names) - 0.5, 1.03, "koliko se razilazi pet eksperata", fontsize=8,
              color="#cc4444", ha="right")

    axes.set_xticks(list(positions), names, rotation=35, ha="right", fontsize=8)
    axes.set_ylabel("raznovrsnost, kao udeo ljudskog neslaganja")
    axes.set_title("Raznovrsnost predloga naspram ljudske skale")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw the phase 3 figures.")
    parser.parse_args()

    summaries = load(RESULTS)
    if not summaries:
        print(f"no evaluation results in {RESULTS}")
        return 1

    FIGURES.mkdir(parents=True, exist_ok=True)
    hit_rate_curve(summaries, FIGURES / "hit-rate-curve.png")
    diversity(summaries, FIGURES / "diversity.png")
    closeness(summaries, FIGURES / "closeness.png")

    print(f"arms {len(summaries)}: {', '.join(summaries)}")
    print(f"written to {FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
