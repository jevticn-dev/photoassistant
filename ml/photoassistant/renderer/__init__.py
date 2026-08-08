"""Renderer — deterministic application of a recipe to an image (NumPy).

Filled in **phase 1**, but only **after** ``docs/RENDERER_SPEC.md``: the
specification is written before the code, because it is the source of truth for
both implementations.

The renderer is a function ``(image float32 RGB, recipe) -> image``. No state, no
network calls, no randomness.

This implementation serves fitting at 512px, recommendation thumbnails and
full-resolution export. The second implementation is a WebGL2 shader in
``frontend/src/app/renderer/`` and translates the **same** specification.

Invariants that do not change without an ADR:

* the operation order is fixed (plan §4.1), with reserved slots for HSL and
  split toning
* physical operations (white balance, exposure) work in **linear** space,
  perceptual ones (tone regions, contrast, curve, colour) in **gamma** space
* the tone curve goes through a **1024-entry LUT** built by one shared
  algorithm; both implementations only interpolate linearly over that table
* the golden agreement test must pass: mean ΔE < 1, maximum < 3
"""

from photoassistant.renderer.color import (
    ciede2000,
    delta_e,
    luma,
    srgb_decode,
    srgb_encode,
    srgb_to_lab,
)
from photoassistant.renderer.curve import LUT_SIZE, apply_lut, build_lut
from photoassistant.renderer.pipeline import quantise, render

__all__ = [
    "LUT_SIZE",
    "apply_lut",
    "build_lut",
    "ciede2000",
    "delta_e",
    "luma",
    "quantise",
    "render",
    "srgb_decode",
    "srgb_encode",
    "srgb_to_lab",
]
