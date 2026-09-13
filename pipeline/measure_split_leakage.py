"""What it cost that the split was drawn *after* the scaling constants (phase 3, task 2).

    uv run --project ml python -m pipeline.measure_split_leakage

The thirty numbers of a fingerprint come from incompatible units, so each one is
centred and divided by its own spread across the corpus (§B43). Those constants
were measured in phase 2 over **all** 24.981 fitted examples — including the 2.481
that belong to the 500 photographs now held out. A held-out photograph therefore
contributed, very slightly, to the scale on which it is later measured.

That is leakage. It is small, and being small is not the same as being known, so
it gets a number rather than a reassurance. Phase 2 paid for exactly this
distinction once already: "a sample of 2.000 gives constants accurate to within
two percent" was an estimate written as a fact, and the measurement said 2,56%
median and 9,57% worst (§B52).

**Measured without a single image.** The column holds ``(raw - mean) / deviation``,
so the raw values come back by inverting that formula. The constants can then be
re-measured over the build set alone and every fingerprint re-scaled with them.
What is reported is how far the **distances** move, because distances are what the
recommender actually uses — a shift that moves every vector the same way changes
nothing.

Decision rule, fixed before the run: **below 1% median shift the leakage is
declared negligible, with the number**; above it, the column is recomputed over
the build set before the ablation starts.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from photoassistant.embeddings.fingerprint import COMPONENT_NAMES, Scaling
from photoassistant.recommender import EvaluationSplit
from photoassistant.storage import DatabaseConfig, connection

from pipeline.environment import REPOSITORY_ROOT, load
from pipeline.make_split import SPLIT_PATH

SCALING_FILE = REPOSITORY_ROOT / "pipeline/reports/fingerprint_scaling.json"

REPORT = Path(
    os.environ.get("LEAKAGE_REPORT") or REPOSITORY_ROOT / "pipeline/reports/split_leakage.json"
)

# The threshold this measurement is judged against, written down before it runs.
NEGLIGIBLE_BELOW_PERCENT = 1.0

# How many random pairs of fingerprints the distance comparison draws. 200.000 is
# far more than the recommender ever compares in one query and costs a second;
# the seed is fixed so the number in the report can be reproduced.
PAIR_SAMPLE = 200_000
PAIR_SEED = 20260913

FINGERPRINTS_SQL = """
SELECT p.source_reference, e.style_fingerprint::text
  FROM examples e
  JOIN photos p ON p.id = e.photo_id
 WHERE e.style_fingerprint IS NOT NULL
 ORDER BY p.source_reference, e.expert
"""


def read_fingerprints(handle) -> tuple[list[str], np.ndarray]:
    """Every stored fingerprint, with the photograph each one belongs to.

    Read as text and parsed here rather than through the ``pgvector`` adapter, for
    the same reason ``embed_all`` writes them as text: the literal format is
    ``[1,2,3]`` and stable, and this keeps one package out of the pipeline's
    dependencies for three lines of work.
    """
    with handle.cursor() as cursor:
        cursor.execute(FINGERPRINTS_SQL)
        rows = cursor.fetchall()

    references = [reference for reference, _ in rows]
    vectors = np.array(
        [np.fromstring(literal.strip("[]"), sep=",") for _, literal in rows],
        dtype=np.float64,
    )
    return references, vectors


def percentiles(values: np.ndarray) -> dict[str, float]:
    return {
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "p99": float(np.percentile(values, 99)),
        "worst": float(values.max()),
    }


def compare_distances(old: np.ndarray, new: np.ndarray) -> dict[str, object]:
    """How much pairwise distances move when the constants change.

    Relative change, on random pairs. Pairs rather than every distance because
    24.981 vectors make 312 million pairs and the answer does not need all of
    them; random rather than nearest because the question is about the space as a
    whole, and the ablation compares candidates from the same pool anyway.
    """
    generator = np.random.default_rng(PAIR_SEED)
    left = generator.integers(0, len(old), PAIR_SAMPLE)
    right = generator.integers(0, len(old), PAIR_SAMPLE)
    keep = left != right
    left, right = left[keep], right[keep]

    before = np.linalg.norm(old[left] - old[right], axis=1)
    after = np.linalg.norm(new[left] - new[right], axis=1)

    relative = np.abs(after - before) / before * 100.0
    return {
        "pairs": int(len(before)),
        "relative_change_percent": percentiles(relative),
        "mean_distance_before": float(before.mean()),
        "mean_distance_after": float(after.mean()),
    }


def compare_constants(old: Scaling, new: Scaling) -> dict[str, object]:
    """Per-component ratio of the two sets of constants, and the worst offender."""
    ratio = new.deviation / old.deviation
    drift = np.abs(new.mean - old.mean) / old.deviation  # in units of a deviation

    worst = int(np.argmax(np.abs(ratio - 1.0)))
    return {
        "deviation_ratio": {
            "median": float(np.median(ratio)),
            "minimum": float(ratio.min()),
            "maximum": float(ratio.max()),
        },
        "worst_component": {
            "name": COMPONENT_NAMES[worst],
            "deviation_ratio": float(ratio[worst]),
            "mean_shift_in_deviations": float(drift[worst]),
        },
        "mean_shift_in_deviations": percentiles(drift),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the leakage from constants that predate the split."
    )
    parser.parse_args()

    load()

    split = EvaluationSplit.load(SPLIT_PATH)
    committed = Scaling.load(SCALING_FILE)

    with connection(DatabaseConfig.from_environment()) as handle:
        references, stored = read_fingerprints(handle)

    if not len(stored):
        print("no fingerprints in the database", file=sys.stderr)
        return 1

    held_out = split.held_out_set
    is_build = np.array([reference not in held_out for reference in references])

    raw = committed.invert_stack(stored)
    rebuilt = Scaling.fit(raw[is_build])
    restated = rebuilt.apply_stack(raw)

    distances = compare_distances(stored, restated)
    constants = compare_constants(committed, rebuilt)
    median_shift = distances["relative_change_percent"]["median"]
    negligible = median_shift < NEGLIGIBLE_BELOW_PERCENT

    report = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fingerprints": int(len(stored)),
        "from_build_set": int(is_build.sum()),
        "from_held_out": int((~is_build).sum()),
        "threshold_percent": NEGLIGIBLE_BELOW_PERCENT,
        "negligible": bool(negligible),
        "distances": distances,
        "constants": constants,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    change = distances["relative_change_percent"]
    ratio = constants["deviation_ratio"]
    worst = constants["worst_component"]

    print(
        f"fingerprints        {len(stored)}  "
        f"({is_build.sum()} build / {(~is_build).sum()} held out)"
    )
    print(f"deviation ratio     median {ratio['median']:.4f}   range {ratio['minimum']:.4f}"
          f" .. {ratio['maximum']:.4f}")
    print(f"worst component     {worst['name']}  ratio {worst['deviation_ratio']:.4f}")
    print(f"distance change %   median {change['median']:.3f}   p99 {change['p99']:.3f}"
          f"   worst {change['worst']:.3f}")
    print()
    print(
        f"{'NEGLIGIBLE' if negligible else 'NOT NEGLIGIBLE'} - median shift "
        f"{median_shift:.3f}% against a threshold of {NEGLIGIBLE_BELOW_PERCENT}%"
    )
    if not negligible:
        print(
            "The constants must be recomputed over the build set, together with every "
            "fingerprint, before the ablation starts.",
            file=sys.stderr,
        )
    print(f"written to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
