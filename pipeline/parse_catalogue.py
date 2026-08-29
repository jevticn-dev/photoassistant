"""Read the FiveK catalogue into a staging file (phase 2, task 2).

    uv run --project ml python -m pipeline.parse_catalogue

Produces two JSONL files under the work directory: one line per photograph and
one line per edit. Nothing else in the pipeline reads the catalogue after this.

**Why a file and not a table.** Parsing the whole catalogue takes seconds and can
be repeated at any time, so a staging table would buy no restartability that is
not already free, and would cost a migration. The file is also an artefact a
person can open and read, which a table in a container is not.

**Why this exists at all**, given that recipes come from fitting and not from the
catalogue (ADR-2). Three reasons, none of them "to get the recipe":

1. the translated parameters are the optimiser's **second starting point**;
2. the catalogue is the only place that says which edits the schema **cannot
   represent** — a grayscale conversion or a brush stroke is invisible in the
   image pair, which just looks like an edit we fitted badly;
3. it carries the **semantic labels** that end up in ``photos.tags``.
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

from pipeline.environment import REPOSITORY_ROOT, load
from pipeline.fivek import catalogue, mapping

PHOTOS_FILE = "photos.jsonl"
EDITS_FILE = "edits.jsonl"


def staging_dir() -> Path:
    return Path(os.environ.get("STAGING_DIR", REPOSITORY_ROOT / "pipeline/.work/staging"))


def main() -> None:
    load()

    raw_root = os.environ.get("FIVEK_DATASET_PATH", "")
    if not raw_root:
        sys.exit("FIVEK_DATASET_PATH is not set")
    dataset = Path(raw_root)

    path = catalogue.locate(dataset)
    print(f"catalogue: {path}")

    connection = catalogue.open_readonly(path)
    try:
        edits, baseline = catalogue.read_edits(connection)
        tags = catalogue.read_tags(connection)
    finally:
        connection.close()

    references = sorted(baseline)
    print(f"photographs {len(references)}  edits {len(edits)}  tagged {len(tags)}")

    destination = staging_dir()
    destination.mkdir(parents=True, exist_ok=True)

    with (destination / PHOTOS_FILE).open("w", encoding="utf-8") as handle:
        for reference in references:
            handle.write(
                json.dumps(
                    {"reference": reference, "tags": tags.get(reference, {})},
                    ensure_ascii=False,
                )
                + "\n"
            )

    excluded = Counter()
    notes = Counter()
    failures = Counter()

    with (destination / EDITS_FILE).open("w", encoding="utf-8") as handle:
        for edit in sorted(edits, key=lambda item: (item.reference, item.expert)):
            if edit.excluded_reason:
                excluded[edit.excluded_reason] += 1
            notes.update(edit.notes)

            record: dict[str, object] = {
                "reference": edit.reference,
                "expert": edit.expert,
                "excluded_reason": edit.excluded_reason,
                "notes": list(edit.notes),
            }
            try:
                # The translation is a starting point, not an answer, so a single
                # edit that will not translate must not stop the pass. It is
                # recorded without one and the fit starts from the neutral
                # offsets alone.
                recipe = mapping.translate(edit.settings, baseline.get(edit.reference, {}))
                record["analytic"] = recipe.model_dump(by_alias=True)
            except Exception as error:  # noqa: BLE001 - reported, not swallowed
                failures[type(error).__name__] += 1
                record["analytic"] = None
                record["analytic_error"] = f"{type(error).__name__}: {error}"

            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nwritten: {destination / PHOTOS_FILE}")
    print(f"written: {destination / EDITS_FILE}")
    print(f"\nexcluded from fitting: {sum(excluded.values())}  {dict(excluded)}")
    print(f"noted but still fitted: {dict(notes)}")
    if failures:
        print(f"translation failures: {dict(failures)}")


if __name__ == "__main__":
    main()
