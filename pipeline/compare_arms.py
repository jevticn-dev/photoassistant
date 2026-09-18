"""Compare two arms photograph by photograph, on the test fixed before the run.

    uv run --project ml python -m pipeline.compare_arms top-per-scene top-per-scene-bestfit

Two arms scored over the same photographs are **paired data**: every photograph is
one question both arms answered, so the comparison is between the two answers to
each question, not between two piles of numbers. Pairing is what makes a small
difference readable at all — photographs differ from each other far more than the
arms differ from each other, and comparing unpaired medians throws that away.

**The test is the sign test**, and its assumption is worth stating because it is
almost nothing: it counts how often one arm beat the other and asks whether that
split could come from a coin. It says nothing about how the differences are
distributed, which matters here, since closeness has a long right tail (a handful
of photographs where nothing in the pool is close) that would drag a mean-based
test around.

Ties are dropped rather than split. A photograph where both arms picked the same
edit carries no evidence either way, and counting it as half a win for each side
would dilute the result toward "no difference" in proportion to how often the two
arms agree — which is a property of the arms, not of the evidence.

The mean difference and its interval are reported **beside** the test, not as it,
so the phase 3 figure has something to be compared against directly.

Reads ``EVALUATION_DIR`` like ``pipeline.evaluate``, so a confirmation run kept in
its own directory is compared without touching the committed summaries.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from pipeline.evaluate import RESULTS, ROWS

# The measure the comparison is about. Named once, here, rather than passed in:
# choosing the metric after seeing the numbers is the thing this whole run exists
# to avoid (DECISIONS.md, ADR-25; notes §B87).
METRIC = "closeness_delta_e"

CONFIDENCE = 0.95


def load_rows(arm: str) -> dict[str, float]:
    """Every scored photograph of one arm, keyed by reference.

    Rows that failed or carry no value for the metric are left out here and
    counted by the caller: a pair needs both halves, and a silently missing half
    would quietly change which photographs the comparison is over.
    """
    path = ROWS / f"{arm}.json"
    if not path.is_file():
        sys.exit(f"no rows for arm {arm!r} at {path}. Run pipeline.evaluate first.")

    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["reference"]: float(row[METRIC])
        for row in rows
        if row.get("outcome") == "done" and row.get(METRIC) is not None
    }


def compare(first: dict[str, float], second: dict[str, float]) -> dict[str, Any]:
    """The paired comparison. ``first`` minus ``second``, so positive favours ``second``.

    The direction is fixed by the argument order and stated in the output rather
    than inferred from which number is larger, because "which arm won" is exactly
    the thing a reader should not have to reconstruct.
    """
    shared = sorted(set(first) & set(second))
    differences = np.array([first[reference] - second[reference] for reference in shared])

    wins = int(np.sum(differences > 0))  # second arm nearer the expert
    losses = int(np.sum(differences < 0))
    ties = int(np.sum(differences == 0))

    decisive = wins + losses
    test = stats.binomtest(wins, decisive, 0.5, alternative="two-sided") if decisive else None

    mean = float(np.mean(differences))
    # Interval on the mean difference, Student's t over the paired differences —
    # the same quantity phase 3 reported, so the two can be read side by side.
    half_width = (
        float(stats.t.ppf(0.5 + CONFIDENCE / 2, len(differences) - 1))
        * float(stats.sem(differences))
        if len(differences) > 1
        else float("nan")
    )

    return {
        "photographs": len(shared),
        "only_in_first": sorted(set(first) - set(second)),
        "only_in_second": sorted(set(second) - set(first)),
        "median_first": float(np.median([first[r] for r in shared])),
        "median_second": float(np.median([second[r] for r in shared])),
        "median_difference": float(np.median(differences)),
        "mean_difference": mean,
        "confidence": CONFIDENCE,
        "mean_difference_low": mean - half_width,
        "mean_difference_high": mean + half_width,
        "second_better": wins,
        "first_better": losses,
        "identical": ties,
        "p_value": float(test.pvalue) if test else float("nan"),
    }


def report(first_arm: str, second_arm: str, result: dict[str, Any]) -> None:
    print(f"metric      {METRIC}, lower is better")
    print(f"paired over {result['photographs']} photographs")
    for label, arm in (("only in", first_arm), ("only in", second_arm)):
        key = "only_in_first" if arm == first_arm else "only_in_second"
        if result[key]:
            print(f"{label} {arm}: {len(result[key])} photographs, not paired")
    print()
    print(f"  {first_arm:<24} median {result['median_first']:.3f}")
    print(f"  {second_arm:<24} median {result['median_second']:.3f}")
    print()
    print(
        f"paired difference ({first_arm} - {second_arm}): "
        f"median {result['median_difference']:+.3f}, mean {result['mean_difference']:+.3f}"
    )
    print(
        f"  {int(result['confidence'] * 100)}% interval on the mean  "
        f"[{result['mean_difference_low']:+.3f}, {result['mean_difference_high']:+.3f}]"
    )
    print()
    print(
        f"sign test   {second_arm} better {result['second_better']}x, "
        f"{first_arm} better {result['first_better']}x, "
        f"identical {result['identical']}x"
    )
    print(f"            p = {result['p_value']:.6g}  (two-sided)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Paired comparison of two evaluated arms.")
    parser.add_argument("first", help="the baseline arm")
    parser.add_argument("second", help="the arm under test; a positive difference favours it")
    parser.add_argument(
        "--out",
        type=Path,
        help="where to write the comparison (default: EVALUATION_DIR/comparison-<a>-vs-<b>.json)",
    )
    arguments = parser.parse_args()

    first = load_rows(arguments.first)
    second = load_rows(arguments.second)
    if not (set(first) & set(second)):
        sys.exit("the two arms share no scored photographs")

    result = compare(first, second)
    report(arguments.first, arguments.second, result)

    destination = arguments.out or RESULTS / (
        f"comparison-{arguments.first}-vs-{arguments.second}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "first": arguments.first,
                "second": arguments.second,
                "metric": METRIC,
                **result,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwritten to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
