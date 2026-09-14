"""How long a recommendation actually takes (phase 3, task 15).

    uv run --project ml --extra service --extra embeddings python -m pipeline.measure_latency

ADR-7 makes recommendations a **synchronous** call: the user waits. That only holds
while the wait is short, and the budget was written down before this ran — **p95
under 1,5 s** on this machine.

**One process, nothing else running.** The latency figures inside the ablation runs
are not usable for this: they were measured while eight workers fought over eight
cores, and the two-stage arm came out at 2,17 s against an expected 0,35. A number
that says what a user waits has to be measured the way a user arrives — alone.

The end-to-end figure goes through the real route with the real encoder and the
real database. Only the network hop is missing, which on a private compose network
is a millisecond against hundreds.

The breakdown is measured separately, because knowing the total is useless for
deciding what to do about it: rendering three previews and encoding one image are
different problems with different fixes.
"""

import argparse
import io
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from photoassistant.imaging import FIT_SIZE, fit_size_for, resample_area
from photoassistant.recommender import (
    ClipEmbedder,
    PostgresVectorStore,
    Recommender,
    TopCandidates,
)
from photoassistant.renderer import quantise, render, srgb_decode, srgb_encode
from photoassistant.storage import DatabaseConfig, connect
from PIL import Image

from pipeline import derivative_cache
from pipeline.environment import REPOSITORY_ROOT, load
from pipeline.make_split import SPLIT_PATH

REPORT = Path(
    os.environ.get("LATENCY_REPORT") or REPOSITORY_ROOT / "pipeline/reports/latency.json"
)

# Written down before the measurement, as every threshold in this phase was.
BUDGET_P95_SECONDS = 1.5

REQUESTS = 50
WARM_UP = 5


def uploads(count: int) -> list[bytes]:
    """Real photographs, encoded as a browser would send them.

    The held-out set, because those are the photographs the system has never seen —
    the same situation a user's upload is in.
    """
    from photoassistant.recommender import EvaluationSplit

    split = EvaluationSplit.load(SPLIT_PATH)
    payloads = []
    for reference in sorted(split.held_out)[: count + WARM_UP]:
        image = derivative_cache.image(f"fivek/{reference}/pre512.png")
        buffer = io.BytesIO()
        Image.fromarray((image * 255).round().astype(np.uint8)).save(
            buffer, format="JPEG", quality=90
        )
        payloads.append(buffer.getvalue())
    return payloads


def summarise(values: list[float]) -> dict[str, float]:
    array = np.array(values, dtype=np.float64)
    return {
        "median_ms": float(np.median(array) * 1000),
        "mean_ms": float(array.mean() * 1000),
        "p95_ms": float(np.percentile(array, 95) * 1000),
        "max_ms": float(array.max() * 1000),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure POST /recommend, one process.")
    parser.add_argument("--requests", type=int, default=REQUESTS)
    arguments = parser.parse_args()

    load()
    from fastapi.testclient import TestClient
    from service.main import app

    payloads = uploads(arguments.requests)
    client = TestClient(app)

    print(f"warm-up: {WARM_UP} requests (model load, connection, first plans)")
    for payload in payloads[:WARM_UP]:
        response = client.post("/recommend", files={"image": ("photo.jpg", payload, "image/jpeg")})
        response.raise_for_status()

    print(f"measuring {arguments.requests} requests, one at a time")
    end_to_end: list[float] = []
    sizes: list[int] = []
    for index, payload in enumerate(payloads[WARM_UP:], start=1):
        began = time.perf_counter()
        response = client.post("/recommend", files={"image": ("photo.jpg", payload, "image/jpeg")})
        end_to_end.append(time.perf_counter() - began)
        response.raise_for_status()
        sizes.append(len(response.content))
        if index % 10 == 0:
            print(f"  {index}/{arguments.requests}")

    # The breakdown, measured apart from the route: a total says how long, the parts
    # say what to do about it.
    stages: dict[str, list[float]] = {"decode": [], "embed": [], "search": [], "render": []}
    embedder = ClipEmbedder()
    # This one is fresh, so it still owes the model load — a second and a third of
    # it, which would land in the first `embed` sample and drag the mean to three
    # times the median. The route pays that once at start-up, not per request; here
    # it is paid before the clock starts, for the same reason.
    embedder.encode([np.zeros((64, 64, 3), dtype=np.float64)])
    with connect(DatabaseConfig.from_environment()) as connection:
        store = PostgresVectorStore(connection)
        recommender = Recommender(
            embedder=embedder,
            store=store,
            strategy=TopCandidates(one_per_photograph=True, prefer_best_fit=True),
        )
        for payload in payloads[WARM_UP : WARM_UP + 20]:
            began = time.perf_counter()
            with Image.open(io.BytesIO(payload)) as handle:
                decoded = np.asarray(handle.convert("RGB"), dtype=np.float64) / 255.0
            height, width = decoded.shape[:2]
            small = srgb_encode(
                resample_area(srgb_decode(decoded), fit_size_for(height, width, FIT_SIZE))
            )
            stages["decode"].append(time.perf_counter() - began)

            began = time.perf_counter()
            (vector,) = embedder.encode([small])
            stages["embed"].append(time.perf_counter() - began)

            began = time.perf_counter()
            result = recommender.recommend_from_vector(vector, exclude=frozenset())
            stages["search"].append(time.perf_counter() - began)

            began = time.perf_counter()
            for candidate in result.suggestions:
                buffer = io.BytesIO()
                Image.fromarray(quantise(render(small, candidate.recipe))).save(
                    buffer, format="JPEG", quality=85
                )
            stages["render"].append(time.perf_counter() - began)

    report = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "requests": len(end_to_end),
        "budget_p95_seconds": BUDGET_P95_SECONDS,
        "end_to_end": summarise(end_to_end),
        "within_budget": float(np.percentile(end_to_end, 95)) < BUDGET_P95_SECONDS,
        "response_bytes": {
            "median": int(np.median(sizes)),
            "max": int(max(sizes)),
        },
        "stages": {name: summarise(values) for name, values in stages.items()},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    figures = report["end_to_end"]
    print(
        f"\nend to end   median {figures['median_ms']:7.1f} ms   "
        f"p95 {figures['p95_ms']:7.1f} ms   max {figures['max_ms']:7.1f} ms"
    )
    for name, values in report["stages"].items():
        print(f"  {name:<9} median {values['median_ms']:7.1f} ms")
    print(f"response     median {report['response_bytes']['median'] / 1024:.0f} KB")
    print(
        f"\n{'WITHIN' if report['within_budget'] else 'OVER'} the budget of "
        f"{BUDGET_P95_SECONDS} s at p95"
    )
    print(f"written to {REPORT}")
    return 0 if report["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
