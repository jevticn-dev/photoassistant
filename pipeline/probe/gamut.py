"""What sRGB clipping actually costs, in ΔE (phase 1b, ADR-17).

    uv run --project ml python pipeline/probe/gamut.py

``prepare.py`` records the *share* of expert pixels that fall outside sRGB. That
number turned out to be nearly useless on its own: it counts any overshoot,
however small, so an image reads as "61% out of gamut" while the difference a
person would see is negligible.

This measures the thing that matters instead. For every expert rendition:

* convert ProPhoto straight to Lab — the colours the expert actually had
* convert ProPhoto to sRGB, clip, and back to Lab — what we can represent
* ΔE between the two, per pixel

The result is an **irreducible** part of the fitting error: those colours cannot
be reached by anything working in sRGB, so the number belongs beside the residual
rather than inside it.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import tifffile
from numpy.typing import NDArray
from photoassistant.renderer.color import ciede2000
from prophoto import PROPHOTO_TO_SRGB_LINEAR, romm_decode

PREPARED = Path(__file__).parent / "prepare_report.json"
REPORT = Path(__file__).parent / "gamut_report.json"

# sRGB primaries to XYZ under D65, and the CIELAB breakpoint.
_SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
# ProPhoto to XYZ under D65: go to linear sRGB first, then to XYZ. Composing it
# the other way round — with the inverse of the sRGB matrix — applies the inverse
# twice and reports a nonsense ΔE in the thirties.
_ROMM_TO_XYZ_D65 = _SRGB_TO_XYZ @ PROPHOTO_TO_SRGB_LINEAR
_D65 = np.array([0.95047, 1.0, 1.08883])
_DELTA = 6.0 / 29.0


def xyz_to_lab(xyz: NDArray[np.float64]) -> NDArray[np.float64]:
    scaled = xyz / _D65
    f = np.where(scaled > _DELTA**3, np.cbrt(scaled), scaled / (3 * _DELTA**2) + 4 / 29)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])],
        axis=-1,
    )


# Guard at import. ProPhoto white must land on Lab (100, 0, 0) whichever path it
# takes, and both paths must agree on it — an inverted or mis-composed matrix
# fails here instead of quietly reporting an absurd ΔE.
_white_direct = xyz_to_lab(np.ones(3) @ _ROMM_TO_XYZ_D65.T)
if not np.allclose(_white_direct, [100.0, 0.0, 0.0], atol=1e-2):  # pragma: no cover
    raise RuntimeError(f"ProPhoto white does not reach Lab (100, 0, 0): {_white_direct}")


def work_root() -> Path:
    configured = os.environ.get("PROBE_WORK_DIR")
    return Path(configured) if configured else Path(__file__).parents[2] / "pipeline" / ".work"


def cost(path: Path, stride: int = 2) -> dict[str, float]:
    """ΔE between the expert's real colours and the closest sRGB can hold."""
    encoded = tifffile.imread(path)[::stride, ::stride].astype(np.float64) / 65535.0
    linear = romm_decode(encoded)

    # Straight to Lab — the ProPhoto matrix is composed through the same
    # adaptation the sRGB path uses, so only the gamut differs, not the white.
    real = xyz_to_lab(linear @ _ROMM_TO_XYZ_D65.T)
    clipped = xyz_to_lab(np.clip(linear @ PROPHOTO_TO_SRGB_LINEAR.T, 0.0, 1.0) @ _SRGB_TO_XYZ.T)

    difference = ciede2000(real, clipped)
    return {
        "mean": round(float(difference.mean()), 3),
        "median": round(float(np.median(difference)), 3),
        "p99": round(float(np.percentile(difference, 99)), 3),
        "max": round(float(difference.max()), 3),
        "share_over_1": round(float((difference > 1.0).mean()), 4),
        "share_over_3": round(float((difference > 3.0).mean()), 4),
    }


def main() -> None:
    if not PREPARED.is_file():
        sys.exit(f"missing {PREPARED} — run prepare.py first")

    names = [row["basename"] for row in json.loads(PREPARED.read_text(encoding="utf-8"))["photos"]]
    tiffs = work_root() / "tiff" / "expert"

    rows = []
    for position, name in enumerate(names, start=1):
        path = tiffs / f"{name}.tif"
        if not path.is_file():
            continue
        measured = cost(path)
        rows.append({"basename": name, **measured})
        print(
            f"  [{position:3d}/{len(names)}] {name:<40} "
            f"mean {measured['mean']:5.2f}  over 1: {measured['share_over_1'] * 100:5.1f}%  "
            f"over 3: {measured['share_over_3'] * 100:4.1f}%"
        )

    def across(key: str) -> dict[str, float]:
        values = np.array([row[key] for row in rows], dtype=np.float64)
        return {
            "mean": round(float(values.mean()), 3),
            "median": round(float(np.median(values)), 3),
            "max": round(float(values.max()), 3),
        }

    summary = {
        "photographs": len(rows),
        "delta_e_of_clipping": across("mean"),
        "share_of_pixels_over_1": across("share_over_1"),
        "share_of_pixels_over_3": across("share_over_3"),
        "photos": rows,
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"{len(rows)} photographs")
    print(f"  cost of clipping to sRGB   mean dE {summary['delta_e_of_clipping']['mean']:.2f}, "
          f"median {summary['delta_e_of_clipping']['median']:.2f}, "
          f"worst image {summary['delta_e_of_clipping']['max']:.2f}")
    print(f"  pixels above dE 1          mean {summary['share_of_pixels_over_1']['mean'] * 100:.1f}%")
    print(f"  pixels above dE 3          mean {summary['share_of_pixels_over_3']['mean'] * 100:.1f}%")
    print(f"report -> {REPORT}")


if __name__ == "__main__":
    main()
