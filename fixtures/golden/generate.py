"""Generate the recipe corpus the golden agreement test renders.

Run once; the resulting JSON is committed and both implementations read the same
file:

    uv run --project ml python fixtures/golden/generate.py

Committing the corpus rather than generating it on both sides is the same
decision, for the same reason, as the test images in ``fixtures/images/``: two
generators agreeing is a second agreement problem, in the exact place we are
trying to remove one. A shared seed is not enough — it would have to produce
identical floating-point values in Python and in JavaScript.

Why these recipes and not a uniform random sample. The golden test needs a
browser, so it runs over tens of combinations rather than the thousands the
property tests use. That budget is spent where two implementations are most
likely to disagree, not spread evenly:

===========================  ====================================================
Group                        Why it earns a place
===========================  ====================================================
neutral                      the identity: proves the whole path -- PNG decode,
                             texture upload, read-back -- is byte-exact before any
                             arithmetic is compared
the four hand-written        the recipes the rest of the suite already uses, so a
fixtures                     failure here is comparable with everything else
each parameter alone         isolates which operation disagrees, if one does
at both ends
known-dangerous pairs        every defect ADR-20 repaired needed two or three
                             parameters at once; a uniform sample reaches those
                             corners rarely
seeded combinations          the rest of the space, reproducibly
===========================  ====================================================

The seed is fixed so a regenerated file is identical to the committed one, and
every recipe is validated through the schema model before it is written — an
invalid recipe cannot reach the corpus.
"""

import json
import random
from pathlib import Path

from photoassistant.schema import EditRecipe

OUT = Path(__file__).parent / "recipes.json"
EDITS = Path(__file__).parents[1] / "edits"

# Fixed so a regenerated corpus is byte-identical to the committed one.
SEED = 20260827

GROUP_OF = {
    "temperature": "white_balance",
    "tint": "white_balance",
    "exposure": "tone",
    "contrast": "tone",
    "highlights": "tone",
    "shadows": "tone",
    "whites": "tone",
    "blacks": "tone",
    "saturation": "color",
    "vibrance": "color",
}

LIMIT = {name: (5.0 if name == "exposure" else 100.0) for name in GROUP_OF}

# Curves worth rendering: the diagonal is covered by `neutral`, so these are the
# shapes that actually exercise the table. The steep one is deliberate — a steep
# segment magnifies any disagreement beneath it, which is exactly what a golden
# test should be looking at.
CURVES = {
    "linear": [[0.0, 0.0], [1.0, 1.0]],
    "medium_contrast": [
        [0.0, 0.0],
        [32 / 255, 22 / 255],
        [64 / 255, 56 / 255],
        [128 / 255, 128 / 255],
        [192 / 255, 196 / 255],
        [1.0, 1.0],
    ],
    "faded": [[0.0, 0.08], [0.25, 0.28], [0.75, 0.8], [1.0, 0.95]],
    "steep_middle": [[0.0, 0.0], [0.45, 0.1], [0.55, 0.9], [1.0, 1.0]],
}


def recipe(curve: str = "linear", **values: float) -> dict:
    """Build a recipe document from flat keyword arguments, everything else neutral."""
    groups: dict[str, dict[str, float]] = {"white_balance": {}, "tone": {}, "color": {}}
    for key, value in values.items():
        groups[GROUP_OF[key]][key] = round(value, 3)

    return {"schema": 1, **groups, "tone_curve": {"points": CURVES[curve]}}


def named() -> list[tuple[str, dict]]:
    """The deliberate part of the corpus."""
    entries: list[tuple[str, dict]] = [("neutral", recipe())]

    for path in sorted(EDITS.glob("*.json")):
        if path.stem != "neutral":
            entries.append((f"fixture_{path.stem}", json.loads(path.read_text(encoding="utf-8"))))

    for name, limit in LIMIT.items():
        for sign, label in ((1.0, "max"), (-1.0, "min")):
            entries.append((f"{name}_{label}", recipe(**{name: sign * limit})))

    for curve in ("medium_contrast", "faded", "steep_middle"):
        entries.append((f"curve_{curve}", recipe(curve=curve)))

    # Every defect ADR-20 repaired, kept in the corpus so the two implementations
    # are compared exactly where they were both once wrong.
    dangerous: list[tuple[str, dict]] = [
        ("adr20_cyan", recipe(temperature=70.0, contrast=45.0, blacks=-60.0, vibrance=60.0)),
        ("adr20_white_to_black", recipe(exposure=2.0, contrast=100.0)),
        ("adr20_hue_flip", recipe(saturation=-100.0, vibrance=-100.0)),
        ("banding_combination", recipe(tint=-63.5, highlights=58.7, whites=-62.7)),
        ("blown_then_recovered", recipe(exposure=2.0, whites=-100.0)),
        ("blown_then_highlights", recipe(exposure=2.0, highlights=-100.0)),
        ("crushed_then_lifted", recipe(exposure=-2.0, blacks=100.0)),
        ("steep_curve_over_blown", recipe(curve="steep_middle", exposure=1.5, contrast=60.0)),
    ]
    entries.extend(dangerous)

    return entries


def seeded(count: int) -> list[tuple[str, dict]]:
    """The rest of the space, reproducibly."""
    rng = random.Random(SEED)
    entries: list[tuple[str, dict]] = []
    curves = list(CURVES)

    for index in range(count):
        values = {name: rng.uniform(-limit, limit) for name, limit in LIMIT.items()}
        entries.append((f"seeded_{index:02d}", recipe(curve=rng.choice(curves), **values)))

    return entries


def main() -> None:
    entries = named() + seeded(24)

    validated = []
    for name, document in entries:
        # Raises if the corpus would contain something the schema refuses, so an
        # invalid recipe cannot be committed and then puzzle someone later.
        EditRecipe.model_validate(document)
        validated.append({"name": name, "recipe": document})

    names = [entry["name"] for entry in validated]
    assert len(names) == len(set(names)), "duplicate recipe name in the corpus"

    OUT.write_text(
        json.dumps({"recipes": validated}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(validated)} recipes to {OUT}")


if __name__ == "__main__":
    main()
