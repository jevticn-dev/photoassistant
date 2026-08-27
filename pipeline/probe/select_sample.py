"""Choose the photographs the feasibility probe runs on (phase 1b, ADR-16).

    uv run --project ml python pipeline/probe/select_sample.py

Writes ``sample.json`` next to this file. That file is **committed**: it is the
definition of the experiment, and a measurement whose input set cannot be
reproduced is not a measurement.

Selection is a deterministic stride over the sorted list of all 5000 basenames,
not a random draw. A seeded RNG would also be reproducible in principle, but only
against the same Python build — striding is reproducible against nothing but the
input files, and anyone can verify it by hand.

The names come from the two index files shipped with the dataset rather than from
the catalogue: the download URL is keyed by basename, and the catalogue is only
needed later, for the analytic initialisation of the fit.

The two files are also two licences (``LicenseAdobe.txt``, ``LicenseAdobeMIT.txt``
— research use only, no commercial use), so each entry records which one it falls
under.
"""

import json
import os
import sys
from pathlib import Path

# One expert is enough to answer "can the renderer reconstruct an expert edit at
# all". C is the usual choice in the FiveK literature, which makes the numbers
# comparable with published work. All five arrive in phase 2.
EXPERT = "c"

SAMPLE_SIZE = 100

INDEX_FILES = {
    "adobe": "filesAdobe.txt",
    "adobe-mit": "filesAdobeMIT.txt",
}

OUTPUT = Path(__file__).parent / "sample.json"


def dataset_root() -> Path:
    """The dataset path comes from the environment, never from the source.

    `.env` is not loaded automatically here — the probe is a script run by hand,
    so the variable is either exported or passed inline.
    """
    raw = os.environ.get("FIVEK_DATASET_PATH")
    if not raw:
        sys.exit(
            "FIVEK_DATASET_PATH is not set.\n"
            "  Set it to the folder holding filesAdobe.txt, for example:\n"
            '  FIVEK_DATASET_PATH="D:/.../Dataset/fivek_dataset" uv run --project ml '
            "python pipeline/probe/select_sample.py"
        )

    root = Path(raw)
    if not root.is_dir():
        sys.exit(f"FIVEK_DATASET_PATH does not point at a folder: {root}")
    return root


def read_index(root: Path) -> list[tuple[str, str]]:
    """All basenames with the licence each falls under, sorted by name."""
    entries: list[tuple[str, str]] = []

    for licence, filename in INDEX_FILES.items():
        path = root / filename
        if not path.is_file():
            sys.exit(f"missing index file: {path}")

        names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        entries.extend((name, licence) for name in names if name)

    duplicates = len(entries) - len({name for name, _ in entries})
    if duplicates:
        sys.exit(f"the two index files overlap by {duplicates} names, which they should not")

    return sorted(entries)


def main() -> None:
    root = dataset_root()
    everything = read_index(root)

    stride = len(everything) // SAMPLE_SIZE
    chosen = everything[:: stride][:SAMPLE_SIZE]

    if len(chosen) != SAMPLE_SIZE:
        sys.exit(f"stride {stride} produced {len(chosen)} entries, expected {SAMPLE_SIZE}")

    document = {
        "expert": EXPERT,
        "count": len(chosen),
        "drawn_from": len(everything),
        "method": (
            f"every {stride}th entry of the sorted union of "
            f"{' and '.join(INDEX_FILES.values())}"
        ),
        "photos": [{"basename": name, "licence": licence} for name, licence in chosen],
    }

    OUTPUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    by_licence: dict[str, int] = {}
    for _, licence in chosen:
        by_licence[licence] = by_licence.get(licence, 0) + 1

    print(f"chose {len(chosen)} of {len(everything)} photographs, expert {EXPERT.upper()}")
    print(f"  stride     {stride}")
    print(f"  licences   {by_licence}")
    print(f"  written to {OUTPUT}")


if __name__ == "__main__":
    main()
