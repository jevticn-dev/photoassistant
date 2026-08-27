"""Edit schema — model, validation and versioning.

Filled in **phase 1**, following ``docs/edit_schema_v1.md``.

The schema is the single format every part of the system uses to describe an
edit: 11 parameters in 4 groups (``white_balance``, ``tone``, ``color``,
``tone_curve``), all-neutral meaning identity, and a mandatory ``schema`` field.

It exists as three models — this one, the C# model in the backend and the
TypeScript interface in the editor. Agreement between them is **not assumed but
proven**: each parses the same fixture files from ``fixtures/edits/`` and
re-serialising must produce identical JSON.

Hard rule: extensions are **additive only** and require an ADR. A record written
as ``schema: 1`` has to stay readable forever.
"""

from photoassistant.schema.model import (
    MIN_POINT_SPACING,
    SCHEMA_VERSION,
    Color,
    EditRecipe,
    Tone,
    ToneCurve,
    WhiteBalance,
    from_json,
    load,
    to_json,
)

__all__ = [
    "MIN_POINT_SPACING",
    "SCHEMA_VERSION",
    "Color",
    "EditRecipe",
    "Tone",
    "ToneCurve",
    "WhiteBalance",
    "from_json",
    "load",
    "to_json",
]
