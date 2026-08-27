"""Run the feasibility probe and write its numbers (phase 1b, ADR-16).

    uv run --project ml python pipeline/probe/measure.py [limit]

Answers the question the whole of 1b exists for: **can the renderer reconstruct
an expert edit at all**, before a second implementation is built on the
assumption that it can.

Every photograph is fitted twice, from two different starting points:

* from **our** decode of the DNG (ADR-4) — what the product will actually do
* from **Lightroom's** neutral rendition — what the expert actually started from

The gap between the two residuals is the cost of decoding the raw ourselves, the
mentor's question, measured rather than argued. The second fit also answers the
main question in its cleanest form: same decoder on both sides, so nothing but
the renderer's own expressiveness is being measured.

Two baselines make the fitted numbers mean something:

* **doing nothing** — how far apart before and after are to begin with. A fit that
  does not beat this is worthless.
* **the sliders alone** — the tone curve is deliberately left out of this first
  fit, so that "how far do the ten sliders get us" and "how much does the master
  curve add" stay separate. Plan §4.2 claims the curve absorbs most of the
  remainder; keeping them apart is what makes that claim checkable.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from photoassistant.fitting import SCALARS, fit, measure

PREPARED = Path(__file__).parent / "prepare_report.json"
REPORT = Path(__file__).parent / "measure_report.json"


def work_root() -> Path:
    configured = os.environ.get("PROBE_WORK_DIR")
    return Path(configured) if configured else Path(__file__).parents[2] / "pipeline" / ".work"


def summarise(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": round(float(array.mean()), 3),
        "median": round(float(np.median(array)), 3),
        "p90": round(float(np.percentile(array, 90)), 3),
        "min": round(float(array.min()), 3),
        "max": round(float(array.max()), 3),
    }


def main() -> None:
    if not PREPARED.is_file():
        sys.exit(f"missing {PREPARED} — run prepare.py first")

    names = [row["basename"] for row in json.loads(PREPARED.read_text(encoding="utf-8"))["photos"]]
    if len(sys.argv) > 1:
        names = names[: int(sys.argv[1])]

    root = work_root()
    rows: list[dict[str, object]] = []
    began = time.perf_counter()

    for position, name in enumerate(names, start=1):
        before = np.load(root / "before" / f"{name}.npy")
        after = np.load(root / "after" / f"{name}.npy")
        reference = np.load(root / "reference" / f"{name}.npy")

        untouched_ours, _, _ = measure(before, after)
        untouched_theirs, _, _ = measure(reference, after)

        # Four fits: two starting images times sliders-only against
        # sliders-plus-curve. The first axis is the decode question, the second
        # is plan §4.2's claim about what the master curve absorbs.
        sliders_ours = fit(before, after)
        sliders_theirs = fit(reference, after)
        curve_ours = fit(before, after, with_curve=True)
        curve_theirs = fit(reference, after, with_curve=True)

        rows.append(
            {
                "basename": name,
                "untouched_from_ours": round(untouched_ours, 3),
                "untouched_from_theirs": round(untouched_theirs, 3),
                "sliders_from_ours": round(sliders_ours.mean_delta_e, 3),
                "sliders_from_theirs": round(sliders_theirs.mean_delta_e, 3),
                "curve_from_ours": round(curve_ours.mean_delta_e, 3),
                "curve_from_theirs": round(curve_theirs.mean_delta_e, 3),
                "max_curve_from_theirs": round(curve_theirs.max_delta_e, 3),
                "seconds": round(
                    sum(
                        result.seconds
                        for result in (sliders_ours, sliders_theirs, curve_ours, curve_theirs)
                    ),
                    2,
                ),
                "at_bounds": curve_theirs.at_bounds(),
                "recipe": curve_theirs.recipe.to_dict(),
            }
        )

        print(
            f"  [{position:3d}/{len(names)}] {name:<40} "
            f"untouched {untouched_theirs:6.2f} -> sliders {sliders_theirs.mean_delta_e:5.2f} "
            f"-> +curve {curve_theirs.mean_delta_e:5.2f}   (ours {curve_ours.mean_delta_e:5.2f})"
        )

    elapsed = time.perf_counter() - began

    def column(key: str) -> list[float]:
        return [float(row[key]) for row in rows]

    untouched = column("untouched_from_theirs")
    sliders_theirs = column("sliders_from_theirs")
    curve_theirs = column("curve_from_theirs")
    curve_ours = column("curve_from_ours")

    # How much of the distance between before and after the best fit closed.
    explained = [
        1.0 - fitted / start for fitted, start in zip(curve_theirs, untouched, strict=True)
    ]

    # What the master curve adds on top of the ten sliders, as a share of the
    # error the sliders alone were left with. Plan §4.2 claims it absorbs most of
    # the remainder; this is the number that says whether it does.
    curve_gain = [
        1.0 - with_curve / sliders
        for with_curve, sliders in zip(curve_theirs, sliders_theirs, strict=True)
    ]

    pinned: dict[str, int] = {}
    for row in rows:
        for name in row["at_bounds"]:  # type: ignore[union-attr]
            pinned[name] = pinned.get(name, 0) + 1

    values: dict[str, list[float]] = {name: [] for _, name, _ in SCALARS}
    for row in rows:
        recipe = row["recipe"]
        for group, name, _ in SCALARS:
            values[name].append(float(recipe[group][name]))  # type: ignore[index]

    summary = {
        "photographs": len(rows),
        "total_seconds": round(elapsed, 1),
        "fits_per_photograph": 4,
        "seconds_per_fit": round(elapsed / max(1, 4 * len(rows)), 2),
        "untouched": summarise(untouched),
        "sliders_from_theirs": summarise(sliders_theirs),
        "curve_from_theirs": summarise(curve_theirs),
        "sliders_from_ours": summarise(column("sliders_from_ours")),
        "curve_from_ours": summarise(curve_ours),
        "share_of_difference_explained": summarise(explained),
        "curve_gain_over_sliders": summarise(curve_gain),
        "decode_cost": summarise(
            [ours - theirs for ours, theirs in zip(curve_ours, curve_theirs, strict=True)]
        ),
        "parameters_at_bounds": dict(sorted(pinned.items(), key=lambda item: -item[1])),
        "parameter_values": {name: summarise(series) for name, series in values.items()},
        "photos": rows,
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"{len(rows)} photographs, {elapsed / 60:.1f} min, {summary['seconds_per_fit']}s per fit")
    print()
    print(f"  {'':<24} {'their decode':>14} {'our decode':>12}")
    print(f"  {'doing nothing':<24} {summary['untouched']['mean']:14.2f} "
          f"{summarise(column('untouched_from_ours'))['mean']:12.2f}")
    print(f"  {'ten sliders':<24} {summary['sliders_from_theirs']['mean']:14.2f} "
          f"{summary['sliders_from_ours']['mean']:12.2f}")
    print(f"  {'sliders + master curve':<24} {summary['curve_from_theirs']['mean']:14.2f} "
          f"{summary['curve_from_ours']['mean']:12.2f}")
    print()
    print(f"  cost of decoding ourselves   mean dE {summary['decode_cost']['mean']:+6.2f}")
    share = summary["share_of_difference_explained"]
    print(f"  difference explained         mean {share['mean'] * 100:.0f}%, "
          f"median {share['median'] * 100:.0f}%")
    gain = summary["curve_gain_over_sliders"]
    print(f"  curve adds over sliders      mean {gain['mean'] * 100:.0f}%, "
          f"median {gain['median'] * 100:.0f}%")
    print()
    if pinned:
        print("  parameters pinned at their range limits:")
        for name, count in summary["parameters_at_bounds"].items():
            print(f"    {name:<12} {count:3d} of {len(rows)}  ({100 * count / len(rows):.0f}%)")
    else:
        print("  no parameter ever reached its range limit")
    print()
    print(f"report -> {REPORT}")


if __name__ == "__main__":
    main()
