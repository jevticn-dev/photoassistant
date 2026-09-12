"""PV2010 develop settings translated into edit schema v1 (`edit_schema` §4).

**This is not how recipes are produced.** ADR-2 chose to reconstruct the expert's
*result* by fitting, not to translate their parameters, because PV2010 semantics
are undocumented and a translation's error cannot be bounded. The probe measured
the gap: translation closes 39% of the difference, fitting 85%, and translation
is **worse than doing nothing** on 23 of 97 photographs.

What it is for, in this phase, is a **second starting point** for the optimiser.
The probe measured that too, and the result is not the obvious one: as the *only*
start it is worse than a neutral offset (2.18 against 1.77), because a half-right
guess leaves the search in the wrong valley. As an *additional* start, where the
best of several wins, it is worth about 1% and costs nothing that was not already
being spent (report 1b, recommendation 3).

Every mapping below is a place the translation can be wrong in a way nobody can
bound. Four are worth naming:

* ``Shadows`` in PV2010 is the **black point** — today's "Blacks", not shadows.
  Mapping by name would invert the meaning of the most-used parameter.
* ``Contrast`` runs [-50, +100] and has to be rescaled onto our symmetric range.
* ``Temperature`` is absolute Kelvin, so the shift only exists relative to the
  as-shot value. Kelvin is not perceptually even — 500 K matters far more at
  3000 K than at 8000 K — so the shift is taken in **mired**, a million over
  Kelvin, which is roughly even.
* ``Brightness`` has no equivalent at all. It becomes a midtone point on the
  master curve, with a scale factor that is a guess.
"""

from photoassistant.schema import EditRecipe

# Auto renditions carry this instead of a value (`edit_schema` §6). Those
# collections are never read, but a number this size reaching a formula would be
# silent nonsense rather than an error.
AUTO_SENTINEL = -999999

# A mired is a million over Kelvin; equal steps in mired are roughly equal steps
# in appearance. This many mired is taken as the full range of our temperature
# parameter — a first guess, and one the probe was built to test.
MIRED_AT_FULL_SCALE = 100.0

# Lightroom's tint runs about three times as wide as ours.
TINT_SCALE = 100.0 / 150.0

# Brightness has no counterpart; this turns it into a midtone lift on the curve.
BRIGHTNESS_TO_MIDTONE = 0.5 / 150.0

# The only named curve in the catalogue besides Linear, and not a rare one:
# measured over all 25.000 edits, Linear 21.901 (87,6%) and this 3.099 (12,4%),
# which is what `edit_schema` §4 predicted.
MEDIUM_CONTRAST: list[tuple[float, float]] = [
    (0.0, 0.0),
    (32 / 255, 22 / 255),
    (64 / 255, 56 / 255),
    (128 / 255, 128 / 255),
    (192 / 255, 196 / 255),
    (1.0, 1.0),
]

NEUTRAL_CURVE: list[tuple[float, float]] = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]

DEFAULT_KELVIN = 5500.0


def number(settings: dict[str, str], key: str, default: float = 0.0) -> float:
    """One setting as a number, or the neutral default when it is absent.

    **An absent optional key means neutral, not missing data.** Confirmed by the
    fact that zero is never serialised — the recorded minima start at 1
    (`edit_schema` §6). Treating absence as an error would reject most of the
    catalogue.
    """
    raw = settings.get(key)
    if raw is None:
        return default
    try:
        value = float(raw.strip('"'))
    except ValueError:
        return default
    return default if value <= AUTO_SENTINEL else value


def clip(value: float, limit: float = 100.0) -> float:
    return max(-limit, min(limit, value))


def translate(expert: dict[str, str], baseline: dict[str, str]) -> EditRecipe:
    """One expert edit as our schema, by translation alone.

    ``baseline`` is the same photograph's ``InputAsShotZeroed`` settings, needed
    because the white balance the expert chose is only meaningful as a shift from
    what the camera recorded.
    """
    expert_kelvin = number(expert, "Temperature", DEFAULT_KELVIN) or DEFAULT_KELVIN
    baseline_kelvin = number(baseline, "Temperature", expert_kelvin) or expert_kelvin
    mired_shift = 1e6 / expert_kelvin - 1e6 / baseline_kelvin
    # Lower Kelvin cools the image, which is our negative direction.
    temperature = clip(-mired_shift / MIRED_AT_FULL_SCALE * 100.0)
    tint = clip((number(expert, "Tint") - number(baseline, "Tint")) * TINT_SCALE)

    # [-50, +100] onto [-100, +100], so the two halves scale differently.
    raw_contrast = number(expert, "Contrast")
    contrast = clip(raw_contrast if raw_contrast >= 0 else raw_contrast * 2.0)

    points = (
        list(MEDIUM_CONTRAST)
        if expert.get("ToneCurveName", "").strip('"') == "Medium Contrast"
        else list(NEUTRAL_CURVE)
    )

    brightness = number(expert, "Brightness")
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
                "exposure": max(-5.0, min(5.0, number(expert, "Exposure"))),
                "contrast": contrast,
                # Raising PV2010's `Shadows` deepens the blacks, which is our
                # negative direction. This one line is the trap the whole mapping
                # exists to avoid.
                "highlights": clip(-number(expert, "HighlightRecovery")),
                "shadows": clip(number(expert, "FillLight")),
                "whites": 0.0,  # no PV2010 source at all (`edit_schema` §3)
                "blacks": clip(-number(expert, "Shadows")),
            },
            "color": {
                "saturation": clip(number(expert, "Saturation")),
                "vibrance": clip(number(expert, "Vibrance")),
            },
            "tone_curve": {"points": points},
        }
    )
