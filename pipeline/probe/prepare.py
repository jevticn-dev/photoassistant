"""Turn the raw inputs into the 512px triples the probe measures on (phase 1b).

    uv run --project ml python pipeline/probe/prepare.py

Produces three images per photograph, all sRGB float32 in [0, 1], all the same
size and all through the *same* resampling — a comparison between differently
resampled images measures the resampler:

============= ==========================  =======================================
``before``    our own decode of the DNG    what the renderer starts from (ADR-4)
``after``     expert C's rendition         what the fit aims at
``reference`` Lightroom's neutral input    the baseline for the decode question
============= ==========================  =======================================

``reference`` exists because of the mentor's observation: our "before" is not the
image the expert started from, so a poor reconstruction could mean either a weak
model or a different starting point. Having Lightroom's own neutral rendition
splits the measurement in two — input to expert is the renderer's expressiveness
on its own, and our decode to expert adds the decode difference on top.

**Geometry has to be reconciled first.** The three do not arrive on the same grid:

* 96 of 100 differ only by a sensor border, about 0.7%, which Lightroom trims and
  rawpy keeps. The decode is centre-cropped to the rendition's aspect and all
  three are resampled to one target.
* one is rotated relative to our decode, with the raw's own orientation flag
  saying otherwise. Both rotations are tried and the one that matches the neutral
  rendition wins, so a wrong guess cannot pass silently.
* three have a genuinely different aspect — the expert cropped. Those are
  **excluded**: comparing a cropped edit against an uncropped source measures the
  crop, and plan §3 keeps crop out of the look entirely.

Also records the share of expert pixels outside sRGB (ADR-17). That count is a
rough guide only — it counts any overshoot, however small; what the clipping
actually costs is measured in ΔE during the measurement step.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import rawpy
import tifffile
from numpy.typing import NDArray
from prophoto import prophoto_to_srgb, resample_area, srgb_encode

LONGEST_SIDE = 512

# Aspect ratios closer than this count as the same framing; anything further
# apart is a crop, not a border trim.
ASPECT_TOLERANCE = 0.01

SAMPLE = Path(__file__).parent / "sample.json"
REPORT = Path(__file__).parent / "prepare_report.json"


def work_root() -> Path:
    configured = os.environ.get("PROBE_WORK_DIR")
    return Path(configured) if configured else Path(__file__).parents[2] / "pipeline" / ".work"


def dng_index(dataset: Path) -> dict[str, Path]:
    """basename -> DNG path.

    Built by scanning rather than by parsing the ``HQa1to700`` folder names: two
    of those ranges overlap at 1400, so the names are not a reliable key.
    """
    index = {path.stem: path for path in dataset.glob("raw_photos/*/photos/*.dng")}
    if not index:
        sys.exit(f"no DNG files under {dataset / 'raw_photos'}")
    return index


def decode_dng(path: Path) -> NDArray[np.float64]:
    """DNG to **linear** sRGB, neutral, per ADR-4.

    ``use_camera_wb`` keeps the as-shot white balance; ``no_auto_bright`` stops
    libraw applying its own exposure correction, which would silently become part
    of what the fit has to undo. Gamma stays at 1.0 so the resampling can happen
    in linear light — encoding comes afterwards, once, shared with the other two.
    """
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            output_color=rawpy.ColorSpace.sRGB,
            output_bps=16,
            gamma=(1.0, 1.0),
        )
    return np.asarray(rgb, dtype=np.float64) / 65535.0


def centre_crop_to_aspect(image: NDArray[np.float64], aspect: float) -> NDArray[np.float64]:
    """Trim the longer dimension until the aspect matches, taking from both edges.

    Removes the sensor border the rendition does not have. Centred because the
    border sits on all four sides; the residue after this is sub-pixel at 512.
    """
    height, width = image.shape[:2]
    if width / height > aspect:
        keep = round(height * aspect)
        start = (width - keep) // 2
        return image[:, start : start + keep]

    keep = round(width / aspect)
    start = (height - keep) // 2
    return image[start : start + keep, :]


def target_size(height: int, width: int) -> tuple[int, int]:
    scale = LONGEST_SIDE / max(height, width)
    return max(1, round(height * scale)), max(1, round(width * scale))


def finish(linear: NDArray[np.floating], target: tuple[int, int]) -> NDArray[np.float32]:
    """Resample in linear light, then encode and clip — the shared tail."""
    return np.clip(srgb_encode(resample_area(linear, target)), 0.0, 1.0).astype(np.float32)


def orient(decoded: NDArray[np.float64], expert: NDArray[np.float64]) -> NDArray[np.float64] | None:
    """Rotate the decode to the rendition's orientation, or give up.

    Returns None when no rotation makes the aspects agree, which is the crop case.
    When a rotation is needed, both directions are tried and the one closer to the
    expert image wins — a wrong guess would otherwise sail through as a very bad
    fit rather than as an obvious error.
    """
    target_aspect = expert.shape[1] / expert.shape[0]

    if abs(decoded.shape[1] / decoded.shape[0] - target_aspect) < ASPECT_TOLERANCE:
        return decoded

    if abs(decoded.shape[0] / decoded.shape[1] - target_aspect) >= ASPECT_TOLERANCE:
        return None

    size = target_size(*expert.shape[:2])
    reference = resample_area(expert, size)
    candidates = [np.rot90(decoded, k) for k in (1, 3)]
    return min(
        candidates,
        key=lambda candidate: float(
            np.abs(
                resample_area(centre_crop_to_aspect(candidate, target_aspect), size) - reference
            ).mean()
        ),
    )


def main() -> None:
    dataset_path = os.environ.get("FIVEK_DATASET_PATH")
    if not dataset_path:
        sys.exit("FIVEK_DATASET_PATH is not set")
    dataset = Path(dataset_path)

    if not SAMPLE.is_file():
        sys.exit(f"missing {SAMPLE} — run select_sample.py first")

    photos = [
        entry["basename"]
        for entry in json.loads(SAMPLE.read_text(encoding="utf-8"))["photos"]
    ]

    root = work_root()
    tiff_root = root / "tiff"
    index = dng_index(dataset)

    for name in ("before", "after", "reference"):
        (root / name).mkdir(parents=True, exist_ok=True)

    prepared: list[dict[str, object]] = []
    excluded: list[dict[str, str]] = []

    for position, basename in enumerate(photos, start=1):
        label = f"[{position:3d}/{len(photos)}] {basename}"
        sources = {
            "after": tiff_root / "expert" / f"{basename}.tif",
            "reference": tiff_root / "input" / f"{basename}.tif",
        }
        dng = index.get(basename)

        if dng is None or not all(path.is_file() for path in sources.values()):
            excluded.append({"basename": basename, "reason": "inputs missing"})
            print(f"  {label}  EXCLUDED, inputs missing")
            continue

        expert_linear, expert_outside = prophoto_to_srgb(tifffile.imread(sources["after"]))
        input_linear, input_outside = prophoto_to_srgb(tifffile.imread(sources["reference"]))

        decoded = orient(decode_dng(dng), expert_linear)
        if decoded is None:
            excluded.append({"basename": basename, "reason": "different framing, expert cropped"})
            print(f"  {label}  EXCLUDED, expert cropped")
            continue

        size = target_size(*expert_linear.shape[:2])
        aspect = expert_linear.shape[1] / expert_linear.shape[0]

        np.save(
            root / "before" / f"{basename}.npy",
            finish(centre_crop_to_aspect(decoded, aspect), size),
        )
        np.save(root / "after" / f"{basename}.npy", finish(expert_linear, size))
        np.save(root / "reference" / f"{basename}.npy", finish(input_linear, size))

        prepared.append(
            {
                "basename": basename,
                "size": list(size),
                "out_of_gamut_expert": round(expert_outside, 5),
                "out_of_gamut_input": round(input_outside, 5),
            }
        )
        print(f"  {label}  {size[1]}x{size[0]}  out of gamut {expert_outside * 100:5.2f}%")

    shares = [float(row["out_of_gamut_expert"]) for row in prepared]
    summary = {
        "prepared": len(prepared),
        "excluded": excluded,
        "longest_side": LONGEST_SIDE,
        "out_of_gamut_expert": {
            "mean": round(float(np.mean(shares)), 5) if shares else None,
            "median": round(float(np.median(shares)), 5) if shares else None,
            "max": round(float(np.max(shares)), 5) if shares else None,
        },
        "photos": prepared,
    }
    REPORT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"prepared {len(prepared)}, excluded {len(excluded)}")
    for entry in excluded:
        print(f"  {entry['basename']}: {entry['reason']}")
    print(f"report -> {REPORT}")


if __name__ == "__main__":
    main()
