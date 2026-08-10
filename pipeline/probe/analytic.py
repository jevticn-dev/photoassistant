"""Translate Lightroom's own settings into our schema, without fitting.

Implements the mapping table in ``docs/edit_schema_v1.md`` §4. Two uses:

* **A baseline.** ADR-2 chose to reconstruct the *result* rather than translate
  somebody else's parameters, on the grounds that PV2010 semantics are
  undocumented and a translation's error would be uncontrolled. ADR-16 asks for
  the number that tests it: if plain translation is as good as fitting, the
  optimiser is not earning its keep.
* **A starting point.** Plan §4.3 has the fit start here rather than from
  nothing. With local minima confirmed (notes §B8), where the search begins
  changes where it ends.

**The translation is approximate, and that is the point.** ``Exposure``,
``Vibrance`` and ``Saturation`` carry over directly; the rest need judgement:

* ``Shadows`` in PV2010 is the **black point**, today's "Blacks" — not shadows.
  Mapping by name would silently invert the meaning of the most-used parameter.
* ``Contrast`` runs [-50, +100] and has to be rescaled onto our symmetric range.
* ``Temperature`` is absolute Kelvin, so the *shift* needs the as-shot value,
  taken from the ``InputAsShotZeroed`` collection. Kelvin is not perceptually
  even either — a change of 500 K means much more at 3000 K than at 8000 K — so
  the shift is computed in **mired** (a million over Kelvin), which is roughly
  even.
* ``Brightness`` has no equivalent at all. It becomes a midtone point on the
  master curve, with a scale factor that is a guess.
* ``Parametric*`` regions are **not mapped**; they would have to be merged into
  the master curve, and 30% of the sample uses them.

Every one of those is a place where the translation can be wrong in a way nobody
can bound. Measuring how far it lands is exactly how ADR-2 gets checked.
"""

import re
import sqlite3
from pathlib import Path

from photoassistant.schema import EditRecipe

EXPERT_COLLECTION = 930899  # "C"
INPUT_COLLECTION = 943690  # "InputAsShotZeroed" — the as-shot white balance baseline

_PAIR = re.compile(r'(\w+)\s*=\s*("[^"]*"|-?[\d.]+|true|false)')

# A mired is a million over Kelvin. Equal steps in mired are roughly equal steps
# in appearance, which Kelvin is not. This many mired of shift is taken as the
# full range of our temperature parameter — a first guess, and one of the things
# the probe is measuring.
MIRED_AT_FULL_SCALE = 100.0

# Lightroom's tint runs about three times as wide as ours.
TINT_SCALE = 100.0 / 150.0

# Brightness has no counterpart; this turns it into a midtone lift on the curve.
BRIGHTNESS_TO_MIDTONE = 0.5 / 150.0

# FiveK "Medium Contrast", the only named curve in the catalogue besides Linear
# (edit_schema §4): 13 of our 97 photographs use it.
MEDIUM_CONTRAST = [
    (0.0, 0.0),
    (32 / 255, 22 / 255),
    (64 / 255, 56 / 255),
    (128 / 255, 128 / 255),
    (192 / 255, 196 / 255),
    (1.0, 1.0),
]


def read_settings(catalogue: Path, collection: int, wanted: set[str]) -> dict[str, dict[str, str]]:
    """Develop settings per photograph, from one collection. Read-only, always."""
    connection = sqlite3.connect(f"file:{catalogue.as_posix()}?mode=ro", uri=True)
    try:
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
        return {name: dict(_PAIR.findall(text)) for name, text in rows if name in wanted}
    finally:
        connection.close()


def _number(settings: dict[str, str], key: str, default: float = 0.0) -> float:
    """A value, or the neutral default when the key is absent.

    An absent optional key means neutral, not missing data — confirmed by the
    fact that zero is never serialised (edit_schema §6). Auto renditions carry a
    -999999 sentinel; those collections are not read here, but the guard is cheap.
    """
    raw = settings.get(key)
    if raw is None:
        return default
    try:
        value = float(raw.strip('"'))
    except ValueError:
        return default
    return default if value <= -999999 else value


def _clip(value: float, limit: float = 100.0) -> float:
    return max(-limit, min(limit, value))


def translate(expert: dict[str, str], as_shot: dict[str, str]) -> EditRecipe:
    """One expert edit, as our schema, by translation alone."""
    # White balance: the shift from as-shot, in mired.
    expert_kelvin = _number(expert, "Temperature", 5500.0) or 5500.0
    baseline_kelvin = _number(as_shot, "Temperature", expert_kelvin) or expert_kelvin
    mired_shift = 1e6 / expert_kelvin - 1e6 / baseline_kelvin
    # Lower Kelvin cools the image, which is our negative direction.
    temperature = _clip(-mired_shift / MIRED_AT_FULL_SCALE * 100.0)
    tint = _clip((_number(expert, "Tint") - _number(as_shot, "Tint")) * TINT_SCALE)

    # Contrast: [-50, +100] onto [-100, +100], so the two halves scale differently.
    raw_contrast = _number(expert, "Contrast")
    contrast = _clip(raw_contrast if raw_contrast >= 0 else raw_contrast * 2.0)

    # `Shadows` is the black point. Raising it deepens blacks, which is our
    # negative direction — the trap this whole mapping exists to avoid.
    blacks = _clip(-_number(expert, "Shadows"))
    highlights = _clip(-_number(expert, "HighlightRecovery"))
    shadows = _clip(_number(expert, "FillLight"))

    points = (
        list(MEDIUM_CONTRAST)
        if expert.get("ToneCurveName", "").strip('"') == "Medium Contrast"
        else [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]
    )

    brightness = _number(expert, "Brightness")
    if brightness:
        lift = max(-0.45, min(0.45, brightness * BRIGHTNESS_TO_MIDTONE))
        points = [
            (x, y if x in (0.0, 1.0) else max(0.0, min(1.0, y + lift * (1.0 - abs(2 * x - 1)))))
            for x, y in points
        ]

    return EditRecipe.model_validate(
        {
            "schema": 1,
            "white_balance": {"temperature": temperature, "tint": tint},
            "tone": {
                "exposure": max(-5.0, min(5.0, _number(expert, "Exposure"))),
                "contrast": contrast,
                "highlights": highlights,
                "shadows": shadows,
                "whites": 0.0,  # no PV2010 source (edit_schema §3)
                "blacks": blacks,
            },
            "color": {
                "saturation": _clip(_number(expert, "Saturation")),
                "vibrance": _clip(_number(expert, "Vibrance")),
            },
            "tone_curve": {"points": points},
        }
    )


def recipes_for(catalogue: Path, basenames: set[str]) -> dict[str, EditRecipe]:
    expert = read_settings(catalogue, EXPERT_COLLECTION, basenames)
    as_shot = read_settings(catalogue, INPUT_COLLECTION, basenames)
    return {
        name: translate(settings, as_shot.get(name, {})) for name, settings in expert.items()
    }
