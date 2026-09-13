"""Draw the 4.500 / 500 evaluation split, once (phase 3, task 1).

    uv run --project ml python -m pipeline.make_split
    uv run --project ml python -m pipeline.make_split --verify

The sample is drawn from the photographs that can actually serve as an exam
question: those with **at least two fitted examples**. Two, not one, because the
diversity threshold is read from how far the experts on the same photograph are
from each other, and a single expert disagrees with nobody. Three photographs have
all five of their edits excluded (rotation, grayscale) and four have four; the
first three are therefore not eligible, the other four are.

They stay in the database either way. Being ineligible as a *question* has nothing
to do with being available as an *answer*: their CLIP vectors are still searched,
they just contribute fewer candidate edits.

**This script refuses to overwrite an existing split.** Not caution for its own
sake — a second draw over the same corpus is a second experiment, and silently
replacing the first would leave every number measured before it describing a split
that no longer exists.
"""

import argparse
import json
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from photoassistant.recommender import HELD_OUT_COUNT, EvaluationSplit, SplitError
from photoassistant.storage import DatabaseConfig, connection

from pipeline.environment import REPOSITORY_ROOT, load

# Overridable for the same reason as EMBED_REPORT and PUBLISH_REPORT in phase 2:
# a test must not be able to overwrite the committed artefact it is reading.
SPLIT_PATH = Path(
    os.environ.get("EVALUATION_SPLIT") or REPOSITORY_ROOT / "pipeline/reports/evaluation_split.json"
)

# The seed lives in configuration, as plan §10 asks. It has a default so that the
# split can be drawn without ceremony; what makes the result reproducible is the
# written file, not this number (see photoassistant.recommender.split).
DEFAULT_SEED = 20260913

# An eligible photograph needs two experts to disagree with each other.
MINIMUM_FITTED_EXAMPLES = 2

CANDIDATES_SQL = """
SELECT p.source_reference
  FROM photos p
  JOIN examples e ON e.photo_id = p.id AND NOT e.excluded_from_fitting
 WHERE p.source = 'Fivek' AND p.source_reference IS NOT NULL
 GROUP BY p.source_reference
HAVING count(*) >= %s
 ORDER BY p.source_reference
"""


def seed_from_environment() -> int:
    raw = os.environ.get("EVAL_SEED", "").strip()
    if not raw:
        return DEFAULT_SEED
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"EVAL_SEED is not a number: {raw!r}")


def eligible_references(handle) -> list[str]:
    with handle.cursor() as cursor:
        cursor.execute(CANDIDATES_SQL, (MINIMUM_FITTED_EXAMPLES,))
        return [reference for (reference,) in cursor.fetchall()]


def draw(references: list[str], seed: int, count: int) -> EvaluationSplit:
    """Pick ``count`` references at random, then sort them.

    Sorting the result changes nothing about which photographs were chosen — a
    split is a set — and makes the file readable and its diffs meaningful.
    """
    if len(references) < count:
        sys.exit(f"only {len(references)} eligible photographs, need {count}")

    chosen = random.Random(seed).sample(references, count)
    return EvaluationSplit(
        seed=seed,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        drawn_from=len(references),
        held_out=tuple(sorted(chosen)),
    )


def verify(split: EvaluationSplit, references: list[str]) -> list[str]:
    """Check the split still describes this corpus. Returns the problems found."""
    eligible = set(references)
    problems = []

    missing = sorted(set(split.held_out) - eligible)
    if missing:
        shown = ", ".join(missing[:5])
        problems.append(f"{len(missing)} held-out references are no longer eligible: {shown} ...")

    if split.drawn_from != len(references):
        problems.append(
            f"drawn from {split.drawn_from} photographs, but {len(references)} are eligible now; "
            "the build set is no longer the one that was measured"
        )

    if len(split.held_out) != HELD_OUT_COUNT:
        problems.append(f"split holds {len(split.held_out)} references, expected {HELD_OUT_COUNT}")

    return problems


def report(split: EvaluationSplit, eligible: int) -> None:
    print(f"eligible   {eligible}")
    print(f"held out   {len(split.held_out)}   seed {split.seed}   drawn {split.created_at}")
    print(f"build set  {split.drawn_from - len(split.held_out)}")
    print(f"first five {', '.join(split.held_out[:5])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw or check the 4.500/500 evaluation split.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="check the existing split against the database instead of drawing one",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="draw again and overwrite the existing split (this invalidates earlier results)",
    )
    arguments = parser.parse_args()

    load()
    config = DatabaseConfig.from_environment()

    with connection(config) as handle:
        references = eligible_references(handle)

    if arguments.verify:
        try:
            split = EvaluationSplit.load(SPLIT_PATH)
        except SplitError as error:
            print(f"FAILED  {error}", file=sys.stderr)
            return 1

        problems = verify(split, references)
        report(split, len(references))
        if problems:
            print("\nFAILED", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("\nOK - every held-out photograph is eligible and the corpus is unchanged")
        return 0

    if SPLIT_PATH.is_file() and not arguments.force:
        existing = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
        print(
            f"a split already exists at {SPLIT_PATH}\n"
            f"  drawn {existing.get('created_at')} with seed {existing.get('seed')}, "
            f"{existing.get('held_out_count')} photographs\n"
            "Drawing a second one over the same corpus is a second experiment and invalidates\n"
            "every number measured against the first. Use --verify to check it, or --force if\n"
            "you really mean to replace it.",
            file=sys.stderr,
        )
        return 1

    split = draw(references, seed_from_environment(), HELD_OUT_COUNT)
    split.save(SPLIT_PATH)
    report(split, len(references))
    print(f"\nwritten to {SPLIT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
