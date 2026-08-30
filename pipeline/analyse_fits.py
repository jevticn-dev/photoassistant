"""What the fitted recipes say (phase 2, task 6 — the decision point).

    uv run --project ml python -m pipeline.analyse_fits

Reads every recipe already in ``examples`` and reports the four things the phase
turns on. It does no fitting of its own, so it can be run again at any time, over
a thousand edits or over all of them.

**1. How well the renderer reconstructs an expert edit.** Comparable with the
probe's 1.68 mean and 1.59 median, but now across all five experts rather than
one.

**2. Whether any parameter piles up at its limit.** A value pinned at ±100 rarely
means the edit was extreme; it usually means that parameter's scale is too weak
to express what the expert did, and the optimiser pushed it as far as it would
go. That is exactly the signal that produced ADR-19, where widening the white
balance halved the worst case.

**3. The banding question — ADR-20, decision B.** The tone-region masks have an
edge 0.25 wide, and over it a strong slider pushes down faster than brightness
rises, so a smooth gradient reverses locally and a band appears in a sky. The
total shift is the **sum** of four masked contributions, so their slopes add and
a combination is worse than any single slider.

The existing measurement used 3000 recipes drawn **independently** in the ranges
the probe fitted, giving median 0, 99th percentile 24, worst 60 and 2.1% of
recipes above 12 steps. Independence is the assumption worth testing: real edits
may correlate their regional values in a way random draws cannot. That is what
this reads off the fitted recipes, and it is the only number the decision needs
that could not be had before phase 2.

**4. What the master curve adds over the sliders**, where the fit measured it.
Plan §4.2 claims the curve "absorbs most of the remainder"; the probe measured
37%, and this checks the claim on ten times the sample.
"""

import json
import os
from collections import Counter

import numpy as np
from photoassistant.renderer import quantise, render
from photoassistant.schema import EditRecipe
from photoassistant.storage import DatabaseConfig, connect

from pipeline.environment import load

# Every 8-bit grey level in order: the densest brightness input there is, and the
# same probe the property test uses, so the numbers are comparable.
WEDGE = np.repeat(
    (np.arange(256, dtype=np.float32) / np.float32(255.0))[:, np.newaxis], 3, axis=1
)[np.newaxis, ...]

# Above this many 8-bit steps of local reversal, a band is visible on a smooth
# gradient. Taken from spec §7.5 so that the two measurements agree on the word.
VISIBLE_STEPS = 12

REGIONAL = ("tint", "highlights", "shadows", "whites", "blacks")


def largest_reversal(recipe: EditRecipe) -> int:
    """Biggest drop in output brightness as input brightness rises, in 8-bit steps.

    Zero means the ordering survived. Anything positive means two pixels came out
    in the opposite order to the one they went in — which on a gradient is a band.
    """
    out = quantise(render(WEDGE, recipe))[0].max(axis=-1).astype(np.int16)
    return int(np.max(np.maximum.accumulate(out) - out))


def percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(len(ordered) * fraction))], 3)

    return {
        "min": round(ordered[0], 3),
        "median": at(0.5),
        "p90": at(0.9),
        "p99": at(0.99),
        "max": round(ordered[-1], 3),
        "mean": round(sum(ordered) / len(ordered), 3),
    }


def read_examples(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.expert, e.fit_error, e.edit, p.source_reference
              FROM examples e
              JOIN photos p ON p.id = e.photo_id
             WHERE NOT e.excluded_from_fitting
            """
        )
        return [
            {
                "expert": expert,
                "fit_error": error,
                "edit": edit if isinstance(edit, dict) else json.loads(edit),
                "reference": reference,
            }
            for expert, error, edit, reference in cursor.fetchall()
        ]


def main() -> None:
    load()

    with connect(DatabaseConfig.from_environment()) as connection:
        rows = read_examples(connection)

    if not rows:
        print("no fitted examples in the database yet")
        return

    print(f"fitted examples: {len(rows)}")
    print(f"by expert: {dict(sorted(Counter(row['expert'] for row in rows).items()))}\n")

    # ---- 1. reconstruction error -----------------------------------------
    errors = percentiles([row["fit_error"] for row in rows])
    print("reconstruction error (mean dE per edit, measured on the full image)")
    print(f"  {errors}")
    print("  probe, expert C only, 97 photographs: mean 1.68  median 1.59  p90 2.58\n")

    # ---- 2. parameters at their limits -----------------------------------
    at_bounds: Counter[str] = Counter()
    values: dict[str, list[float]] = {}
    for row in rows:
        recipe = EditRecipe.model_validate(row["edit"])
        for group in ("white_balance", "tone", "color"):
            block = getattr(recipe, group)
            for name in type(block).model_fields:
                value = float(getattr(block, name))
                values.setdefault(name, []).append(value)
                limit = 5.0 if name == "exposure" else 100.0
                if abs(value) >= limit * 0.98:
                    at_bounds[name] += 1

    print("fitted values per parameter")
    for name, series in values.items():
        share = at_bounds[name] / len(rows)
        stats = percentiles(series)
        print(
            f"  {name:12s} median {stats['median']:>7}  "
            f"range [{stats['min']:>7}, {stats['max']:>7}]  at limit {share:6.1%}"
        )
    print("  probe: whites 5%, blacks 3% at their limits\n")

    # ---- 3. banding, over the joint distribution -------------------------
    reversals = [largest_reversal(EditRecipe.model_validate(row["edit"])) for row in rows]
    visible = [value for value in reversals if value > VISIBLE_STEPS]
    banding = percentiles([float(value) for value in reversals])
    print("banding: largest local reversal, in 8-bit steps out of 255")
    print(f"  {banding}")
    print(f"  above {VISIBLE_STEPS} steps (visible): {len(visible)} of {len(rows)} "
          f"= {len(visible) / len(rows):.2%}")
    print("  3000 independently drawn recipes: median 0  p99 24  max 60  visible 2.1%\n")

    # ---- 4. what the curve adds ------------------------------------------
    curve_moved = sum(
        1
        for row in rows
        if EditRecipe.model_validate(row["edit"]).tone_curve.points
        != [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
    )
    print(f"recipes whose curve is not neutral: {curve_moved} of {len(rows)}")

    report = {
        "examples": len(rows),
        "by_expert": dict(sorted(Counter(row["expert"] for row in rows).items())),
        "reconstruction_error": errors,
        "at_bounds_share": {
            name: round(count / len(rows), 4) for name, count in at_bounds.most_common()
        },
        "parameter_values": {name: percentiles(series) for name, series in values.items()},
        "banding_steps": banding,
        "banding_visible_share": round(len(visible) / len(rows), 4),
        "banding_threshold_steps": VISIBLE_STEPS,
    }
    destination = os.path.join(os.path.dirname(__file__), "fit_analysis.json")
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\nwritten: {destination}")


if __name__ == "__main__":
    main()
