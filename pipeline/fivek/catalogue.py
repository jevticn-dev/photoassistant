"""Reading the FiveK Lightroom catalogue. Read-only, always.

``fivek.lrcat`` is a SQLite database, and the word "catalogue" is misleading: it
holds **no images at all**. It records where each photograph's file is, which
collections it belongs to, what every expert set every slider to, and the
keywords somebody attached (`docs/notes/phase-2-concepts.md` §A9).

**It is opened read-only and nothing else is acceptable.** ``Dataset/`` is an
input; a stray write into a Lightroom catalogue is not recoverable from anything
we have. The connection is opened with ``mode=ro``, which makes the guarantee the
database's rather than the programmer's.

Everything here was checked against the real catalogue on 2026-08-29 rather than
assumed, and the counts agree with the analysis the plan was written from: 25.000
expert edits, 87,6% Linear curve and 12,4% "Medium Contrast", 16 edits with
Clarity, 7 touching the grayscale mixer, 5 cropped.
"""

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Where the catalogue sits relative to the dataset root. It is **inside**
# raw_photos, not next to it — which docs/phases/phase-0.md got slightly wrong,
# and which is exactly the kind of thing worth locating rather than assuming.
CATALOGUE_LOCATIONS = ("raw_photos/fivek.lrcat", "fivek.lrcat")

EXPERTS = ("a", "b", "c", "d", "e")

# The collection holding Lightroom's neutral rendition: as-shot white balance,
# every other slider at zero. It is the "before" the fit starts from (ADR-18) and
# the baseline the white balance shift is measured against.
BEFORE_COLLECTION = "InputAsShotZeroed"

# Auto renditions carry this instead of a value. Their collections are never read
# here, but a value this size reaching a formula would be silent nonsense.
AUTO_SENTINEL = -999999

_PAIR = re.compile(r'(\w+)\s*=\s*("[^"]*"|-?[\d.]+|true|false)')

# Controlled vocabularies, verified by arithmetic against the catalogue: every
# photograph tagged `dof` carries exactly one of the three depth values
# (606 + 232 + 213 = 1051), and every one tagged `dir` exactly one direction
# (162 + 159 + 28 = 349). The marker tag names the field, the value tag fills it.
TAG_FIELDS: dict[str, tuple[str, frozenset[str]]] = {
    "dof": ("depth_of_field", frozenset({"deep", "shallow", "interm"})),
    "dir": ("light_direction", frozenset({"side", "back", "front"})),
    "type": ("light_type", frozenset({"soft", "hard"})),
}

# Subject keywords are prefixed in the catalogue itself, which is what makes them
# safe to keep: nine categories, none of them a person's name.
SUBJECT_PREFIX = "tag:"


class CatalogueError(RuntimeError):
    """The catalogue is missing, or does not look like the one this reads."""


@dataclass(frozen=True)
class Edit:
    """One expert's treatment of one photograph, as the catalogue records it."""

    reference: str
    expert: str
    settings: dict[str, str]
    excluded_reason: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def excluded(self) -> bool:
        return self.excluded_reason is not None


def locate(dataset_root: Path) -> Path:
    """Find the catalogue under the dataset root, or say exactly where it looked."""
    for relative in CATALOGUE_LOCATIONS:
        candidate = dataset_root / relative
        if candidate.is_file():
            return candidate
    looked = ", ".join(str(dataset_root / relative) for relative in CATALOGUE_LOCATIONS)
    raise CatalogueError(f"no fivek.lrcat found. Looked in: {looked}")


def open_readonly(catalogue: Path) -> sqlite3.Connection:
    """Open the catalogue so that writing to it is impossible, not merely avoided."""
    return sqlite3.connect(f"file:{catalogue.as_posix()}?mode=ro", uri=True)


def collection_ids(connection: sqlite3.Connection) -> dict[str, int]:
    """Map collection name to id.

    Looked up rather than hard-coded. The probe carried the literal 930899 for
    expert C, which is fine in a script that ran once and is now a measurement
    record, and wrong here: a number nobody can read is a number nobody notices
    going stale.
    """
    return {
        name: identifier
        for identifier, name in connection.execute(
            "SELECT id_local, name FROM AgLibraryCollection WHERE name IS NOT NULL"
        )
    }


def read_settings(connection: sqlite3.Connection, collection: int) -> dict[str, dict[str, str]]:
    """Develop settings per photograph for one collection, as key/value text."""
    rows = connection.execute(
        """
        SELECT f.baseName, d.text
          FROM AgLibraryCollectionImage ci
          JOIN Adobe_images i               ON i.id_local = ci.image
          JOIN AgLibraryFile f              ON f.id_local = i.rootFile
          JOIN Adobe_imageDevelopSettings d ON d.id_local = i.developSettingsIDCache
         WHERE ci.collection = ? AND d.text IS NOT NULL
        """,
        (collection,),
    )
    return {name: dict(_PAIR.findall(text)) for name, text in rows}


def read_raw_text(connection: sqlite3.Connection, collection: int) -> dict[str, str]:
    """The unparsed settings block, for the structures the key/value regex misses.

    Local corrections are nested tables in the catalogue's Lua-like format, not
    ``key = value`` pairs, so the only reliable way to notice them is to look for
    the structure by name. Measured: two edits carry ``PaintBasedCorrections`` and
    one ``GradientBasedCorrections``, out of 25.000.
    """
    rows = connection.execute(
        """
        SELECT f.baseName, d.text
          FROM AgLibraryCollectionImage ci
          JOIN Adobe_images i               ON i.id_local = ci.image
          JOIN AgLibraryFile f              ON f.id_local = i.rootFile
          JOIN Adobe_imageDevelopSettings d ON d.id_local = i.developSettingsIDCache
         WHERE ci.collection = ? AND d.text IS NOT NULL
        """,
        (collection,),
    )
    return dict(rows)


def read_tags(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Semantic labels per photograph, filtered to what is worth keeping.

    Kept: the nine ``tag:`` subjects, and the three controlled vocabularies above
    as key/value pairs. Discarded: photographers' names, place names, and the
    marker tags themselves — plan §5.2 asks for the useful ones, and a
    photographer's name is a person, not a property of the scene.
    """
    names = {
        identifier: name
        for identifier, name in connection.execute(
            "SELECT id_local, name FROM AgLibraryKeyword"
        )
    }

    per_photo: dict[str, set[str]] = defaultdict(set)
    for reference, tag in connection.execute(
        """
        SELECT f.baseName, ki.tag
          FROM AgLibraryKeywordImage ki
          JOIN Adobe_images i  ON i.id_local = ki.image
          JOIN AgLibraryFile f ON f.id_local = i.rootFile
        """
    ):
        label = names.get(tag)
        if label:
            per_photo[reference].add(label)

    result: dict[str, dict[str, object]] = {}
    for reference, labels in per_photo.items():
        entry: dict[str, object] = {}

        subjects = sorted(
            label[len(SUBJECT_PREFIX) :] for label in labels if label.startswith(SUBJECT_PREFIX)
        )
        if subjects:
            entry["subjects"] = subjects

        for marker, (field_name, vocabulary) in TAG_FIELDS.items():
            if marker not in labels:
                continue
            values = sorted(labels & vocabulary)
            # One value is the whole point of a controlled vocabulary. More than
            # one means the reading of this encoding is wrong, and guessing which
            # to keep would hide that.
            if len(values) == 1:
                entry[field_name] = values[0]

        if entry:
            result[reference] = entry
    return result


def exclusion_reason(settings: dict[str, str], raw: str) -> str | None:
    """Why edit schema v1 cannot represent this edit, or None if it can.

    Three reasons, all of them rare, all of them measured rather than feared:

    ``grayscale``     7 edits touch the grayscale mixer (`edit_schema` §5)
    ``local``         3 carry brush or gradient corrections
    ``crop``          5 were cropped, and plan §3 keeps crop out of the look

    Clarity is **not** here. Sixteen edits use it and the schema does not model
    it, but that is a spatial operation whose absence shows up honestly as
    residual error. Throwing the edits away would hide a known limitation instead
    of measuring it.
    """
    if any(key.startswith("GrayMixer") for key in settings):
        return "grayscale"
    if settings.get("ConvertToGrayscale") == "true":
        return "grayscale"
    if "PaintBasedCorrections" in raw or "GradientBasedCorrections" in raw:
        return "local"
    if any(key.startswith("Crop") for key in settings):
        return "crop"
    return None


def notes_for(settings: dict[str, str]) -> tuple[str, ...]:
    """Things worth recording that do not disqualify the edit.

    Clarity is unmodelled but the edit is still fitted; saying so lets the report
    separate "our model is weak here" from "this edit used something we do not
    have".
    """
    notes = []
    if _has_value(settings, "Clarity"):
        notes.append("clarity")
    if settings.get("ToneCurveName", "").strip('"') == "Medium Contrast":
        notes.append("medium-contrast-curve")
    return tuple(notes)


def _has_value(settings: dict[str, str], key: str) -> bool:
    raw = settings.get(key)
    if raw is None:
        return False
    try:
        return float(raw.strip('"')) != 0.0
    except ValueError:
        return False


def read_edits(connection: sqlite3.Connection) -> tuple[list[Edit], dict[str, dict[str, str]]]:
    """Every expert edit in the catalogue, plus the neutral baseline per photograph.

    The baseline is returned alongside because the white balance mapping needs it:
    ``Temperature`` is an absolute Kelvin value, so the *shift* an expert applied
    only exists relative to what the camera recorded.
    """
    collections = collection_ids(connection)

    missing = [name for name in (*(e.upper() for e in EXPERTS), BEFORE_COLLECTION)
               if name not in collections]
    if missing:
        raise CatalogueError(f"catalogue is missing expected collections: {missing}")

    baseline = read_settings(connection, collections[BEFORE_COLLECTION])

    edits: list[Edit] = []
    for expert in EXPERTS:
        identifier = collections[expert.upper()]
        settings_by_photo = read_settings(connection, identifier)
        raw_by_photo = read_raw_text(connection, identifier)
        for reference, settings in settings_by_photo.items():
            edits.append(
                Edit(
                    reference=reference,
                    expert=expert,
                    settings=settings,
                    excluded_reason=exclusion_reason(settings, raw_by_photo.get(reference, "")),
                    notes=notes_for(settings),
                )
            )
    return edits, baseline
