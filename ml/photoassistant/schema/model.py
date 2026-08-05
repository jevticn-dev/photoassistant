"""The edit schema v1 as a Python model.

Follows ``docs/edit_schema_v1.md``. One of three models of the same format; the
other two are the C# record in the backend and the TypeScript interface in the
editor. Agreement between them is proven over the shared fixtures in
``fixtures/edits/`` rather than assumed.

Two things this module deliberately does:

* **Rejects rather than repairs.** A recipe outside the declared ranges, or with
  a tone curve that breaks the rules in ``RENDERER_SPEC.md`` §6.1, raises. The
  renderer may then assume its input is valid and skip defensive checks in the
  per-pixel path.
* **Always emits every key.** Parsing accepts an omitted group and fills in the
  neutral value, but serialising writes the full document. That keeps the
  canonical form single-valued, which is what makes the three-language
  agreement test meaningful.
"""

import json
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1

# Every parameter but exposure is normalised to the same symmetric interval, so
# that the editor and the fitting loop treat them uniformly (edit_schema §3).
Normalised = Annotated[float, Field(ge=-100.0, le=100.0)]

# Exposure is in stops and keeps physical meaning: +1 is twice the light.
Stops = Annotated[float, Field(ge=-5.0, le=5.0)]

# A curve control point, (input, output), both in [0, 1].
Point = tuple[Annotated[float, Field(ge=0.0, le=1.0)], Annotated[float, Field(ge=0.0, le=1.0)]]


class _Strict(BaseModel):
    """Unknown keys are an error, not something to ignore.

    A misspelled parameter that is silently dropped would render as neutral and
    the difference would surface only as an unexplained fitting residual.
    """

    model_config = ConfigDict(extra="forbid")


class WhiteBalance(_Strict):
    temperature: Normalised = 0.0
    tint: Normalised = 0.0


class Tone(_Strict):
    exposure: Stops = 0.0
    contrast: Normalised = 0.0
    highlights: Normalised = 0.0
    shadows: Normalised = 0.0
    whites: Normalised = 0.0
    blacks: Normalised = 0.0


class Color(_Strict):
    saturation: Normalised = 0.0
    vibrance: Normalised = 0.0


class ToneCurve(_Strict):
    """Control points of the master tone curve, not the curve itself.

    The interpolated curve and its 1024-entry LUT are built by the renderer
    (``RENDERER_SPEC.md`` §6); the schema only carries the points.
    """

    points: list[Point] = [(0.0, 0.0), (1.0, 1.0)]

    @field_validator("points")
    @classmethod
    def _obeys_spec_6_1(cls, points: list[Point]) -> list[Point]:
        if len(points) < 2:
            raise ValueError("a tone curve needs at least two points")

        xs = [x for x, _ in points]
        if xs[0] != 0.0 or xs[-1] != 1.0:
            # Without both endpoints the curve is undefined over part of the
            # input range, and the two implementations would have to invent the
            # same extrapolation rule.
            raise ValueError(f"the first x must be 0.0 and the last 1.0, got {xs[0]} and {xs[-1]}")

        if any(b <= a for a, b in pairwise(xs)):
            raise ValueError(f"x values must increase strictly, got {xs}")

        return points

    def is_neutral(self) -> bool:
        return self.points == [(0.0, 0.0), (1.0, 1.0)]


class EditRecipe(_Strict):
    """One edit, in the format every part of the system speaks.

    All-neutral means identity: rendering a neutral recipe returns the input
    image unchanged, bit for bit (``RENDERER_SPEC.md`` §4.1).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # `schema` shadows a BaseModel attribute name, so the field is `version` and
    # the wire name is set by the alias. Parsing accepts both spellings;
    # serialising always writes `schema`.
    version: int = Field(default=SCHEMA_VERSION, alias="schema")
    white_balance: WhiteBalance = Field(default_factory=WhiteBalance)
    tone: Tone = Field(default_factory=Tone)
    color: Color = Field(default_factory=Color)
    tone_curve: ToneCurve = Field(default_factory=ToneCurve)

    @field_validator("version")
    @classmethod
    def _readable_version(cls, version: int) -> int:
        # edit_schema §7: a reader refuses a schema newer than it understands.
        # Older versions stay readable forever, which is why extensions are
        # additive only.
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema version {version}; this reader understands {SCHEMA_VERSION}"
            )
        return version

    def is_neutral(self) -> bool:
        """True when the recipe is the identity.

        The renderer uses the per-operation skip rule rather than this, but the
        fitting loop and the tests want the whole-recipe answer.
        """
        return self == EditRecipe()

    def to_dict(self) -> dict[str, Any]:
        """The canonical mapping: every key present, in schema order."""
        return self.model_dump(by_alias=True)


def from_json(text: str) -> EditRecipe:
    return EditRecipe.model_validate_json(text)


def to_json(recipe: EditRecipe, *, indent: int = 2) -> str:
    """Serialise to the canonical form, newline-terminated.

    Note what "canonical" can and cannot mean across three languages: key order
    and content are fixed here, but the *text* is not comparable between
    languages, because JavaScript cannot distinguish 0 from 0.0 when
    stringifying. The agreement test therefore compares parsed values, not
    bytes — see ``ml/tests/test_schema_roundtrip.py``.
    """
    return json.dumps(recipe.to_dict(), indent=indent) + "\n"


def load(path: Path) -> EditRecipe:
    return from_json(path.read_text(encoding="utf-8"))
