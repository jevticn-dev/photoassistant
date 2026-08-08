"""The renderer: a recipe applied to an image, in the order the spec fixes.

Implements ``RENDERER_SPEC.md`` §3 to §5. The operation order is locked (plan
§4.1) and changes only through an ADR, because phase 2 fits 25,000 recipes
against exactly this sequence — a reordering would make every stored recipe
describe an edit the renderer no longer performs.

The skip rule (§4.1) is not an optimisation. Steps 1 and 4, decoding to linear
and encoding back, are skipped **together** and only when white balance and
exposure are both neutral. Decode followed by encode is not an exact inverse in
finite precision, so running them without cause would leave a neutral recipe
returning something a few last bits away from its input. With the rule in place a
neutral recipe performs no arithmetic at all, and identity is bit-exact — which is
what ``test_renderer_pipeline.py`` asserts.
"""

import numpy as np
from numpy.typing import NDArray

from photoassistant.renderer import masks
from photoassistant.renderer.color import luma, srgb_decode, srgb_encode
from photoassistant.renderer.curve import apply_lut, build_lut, is_identity
from photoassistant.schema import EditRecipe

# Constants from spec §8.3. Chosen to give a usable range at the ends of each
# scale, not calibrated against data — phase 1b measures whether they are right
# and any correction goes through an ADR (see RENDERER_SPEC.md §10).
K_WB = np.float32(0.5)
K_REG = np.float32(0.25)
EPS = np.float32(1e-6)


def white_balance_multipliers(temperature: float, tint: float) -> NDArray[np.float32]:
    """Per-channel multipliers for the linear stage (spec §3.1).

    Normalising by the multipliers' own luminance is what makes this a purely
    chromatic operation: neutral grey keeps its brightness, and changing the
    overall level stays exposure's job.
    """
    t = np.float32(temperature) / np.float32(100.0)
    u = np.float32(tint) / np.float32(100.0)

    multipliers = np.array(
        [
            np.exp2(K_WB * t),
            np.exp2(-K_WB * u),
            np.exp2(-K_WB * t),
        ],
        dtype=np.float32,
    )

    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return (multipliers / (multipliers * weights).sum(dtype=np.float32)).astype(np.float32)


def tone_region_shift(image: NDArray[np.float32], recipe: EditRecipe) -> NDArray[np.float32]:
    """The combined shift from the four regional parameters (spec §3.3).

    All four weights come from the **same** luma, computed before any of them is
    applied, and the shifts are summed and applied once. That removes the
    question of which regional parameter goes first — and with it one more place
    where two implementations could disagree.
    """
    y = luma(image)
    tone = recipe.tone

    shift = (
        np.float32(tone.highlights / 100.0) * masks.highlights(y)
        + np.float32(tone.shadows / 100.0) * masks.shadows(y)
        + np.float32(tone.whites / 100.0) * masks.whites(y)
        + np.float32(tone.blacks / 100.0) * masks.blacks(y)
    )
    return (K_REG * shift).astype(np.float32)


def apply_contrast(image: NDArray[np.float32], contrast: float) -> NDArray[np.float32]:
    """S-curve about mid grey, as a blend towards smoothstep (spec §3.4).

    Written as a polynomial rather than the usual sigmoid on purpose: a sigmoid
    needs ``asin``, whose last bits differ between NumPy and GLSL, and would spend
    the ΔE budget for nothing. Monotone for every s in [-1, 1] and stays in range.
    """
    s = np.float32(contrast) / np.float32(100.0)
    x = image
    shaped = x * x * (np.float32(3.0) - np.float32(2.0) * x)
    return (x + s * (shaped - x)).astype(np.float32)


def apply_saturation(image: NDArray[np.float32], recipe: EditRecipe) -> NDArray[np.float32]:
    """Saturation and vibrance in one scaling (spec §3.6).

    Both gains are computed from the same pre-change pixel and summed, so neither
    ordering exists. Vibrance is weighted by ``1 - p``: it spares what is already
    saturated, which is the whole difference between it and saturation.
    """
    y = luma(image)[..., np.newaxis]
    highest = image.max(axis=-1, keepdims=True)
    lowest = image.min(axis=-1, keepdims=True)
    saturation_of_pixel = (highest - lowest) / np.maximum(highest, EPS)

    gain = np.float32(recipe.color.saturation / 100.0) + np.float32(
        recipe.color.vibrance / 100.0
    ) * (np.float32(1.0) - saturation_of_pixel)

    return (y + (image - y) * (np.float32(1.0) + gain)).astype(np.float32)


def render(image: NDArray[np.floating], recipe: EditRecipe) -> NDArray[np.float32]:
    """Apply a recipe to an sRGB image in [0, 1], returning a new array.

    Deterministic: same input, same recipe, same output, everywhere. No state, no
    randomness, no clock.
    """
    rgb = np.asarray(image, dtype=np.float32)

    tone = recipe.tone
    white_balance = recipe.white_balance

    skip_white_balance = white_balance.temperature == 0.0 and white_balance.tint == 0.0
    skip_exposure = tone.exposure == 0.0
    skip_regions = (
        tone.highlights == 0.0
        and tone.shadows == 0.0
        and tone.whites == 0.0
        and tone.blacks == 0.0
    )
    skip_contrast = tone.contrast == 0.0
    skip_curve = is_identity(np.asarray(recipe.tone_curve.points, dtype=np.float64))
    skip_colour = recipe.color.saturation == 0.0 and recipe.color.vibrance == 0.0

    # Steps 1 and 4 exist only to serve steps 2 and 3, so they live and die with
    # them. This is the line the bit-exact identity test depends on.
    if not (skip_white_balance and skip_exposure):
        rgb = srgb_decode(rgb)  # 1

        if not skip_white_balance:  # 2
            rgb = rgb * white_balance_multipliers(white_balance.temperature, white_balance.tint)

        if not skip_exposure:  # 3
            rgb = rgb * np.exp2(np.float32(tone.exposure))

        rgb = srgb_encode(rgb)  # 4

    if not skip_regions:  # 5
        rgb = rgb + tone_region_shift(rgb, recipe)[..., np.newaxis]

    if not skip_contrast:  # 6
        rgb = apply_contrast(rgb, tone.contrast)

    if not skip_curve:  # 7
        rgb = apply_lut(build_lut(np.asarray(recipe.tone_curve.points)), rgb)

    # 8 — slot: HSL, schema 2. Empty, and skipped unconditionally.

    if not skip_colour:  # 9
        rgb = apply_saturation(rgb, recipe)

    # 10 — slot: split toning, schema 2. Empty, and skipped unconditionally.

    return np.clip(rgb, np.float32(0.0), np.float32(1.0))  # 11


def quantise(image: NDArray[np.floating]) -> NDArray[np.uint8]:
    """Float in [0, 1] to 8-bit, by the rule both implementations share (§8.4).

    ``readPixels`` on an RGBA8 framebuffer returns integers the GPU has already
    rounded. Rounding differently here would compare a quantised output against a
    continuous one, and the difference would be systematic — every pixel, same
    direction — rather than noise.
    """
    x = np.clip(np.asarray(image, dtype=np.float32), np.float32(0.0), np.float32(1.0))
    return np.floor(x * np.float32(255.0) + np.float32(0.5)).astype(np.uint8)
