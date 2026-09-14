"""The exam itself: every arm over the five hundred hidden photographs (task 9).

    uv run --project ml python -m pipeline.evaluate --list
    uv run --project ml python -m pipeline.evaluate --arm mmr-0.5
    uv run --project ml python -m pipeline.evaluate --all

One photograph goes through the **shipped path** — embed, search, pool, select —
and is then scored twice: how far apart the three suggestions look, and how near
the best of them lands to an expert (§B60).

**Why it is built the way it is.** Measured at the start of the phase: a render is
59 ms and a perceptual comparison 176 ms, of which 56 ms is converting to CIELAB.
Written naively that is 3,35 s per photograph, 28 minutes an arm and seven hours
for the study. Converting each image once and running photographs across processes
brings an arm to about two minutes (§B55). Both are requirements here, not
optimisations:

* every image is converted to Lab **once** and passed around as Lab
* renders are memoised per photograph, so the two-stage arm does not render the
  three survivors a second time for the metric
* derivatives come from the local cache, not from MinIO, after the first pass
* photographs run across processes, never arms — arms share the cache and would
  fight over memory and disk

**The strategy is built inside the worker, from a name.** The two-stage arm holds
a rendering function bound to one photograph, and a closure cannot cross a process
boundary; passing the arm's name and building it on the other side avoids the
question entirely.
"""

import os

# Before NumPy, as everywhere in this pipeline: eight workers each starting a BLAS
# pool sized to the whole machine is slower than running serially (§B27).
for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from numpy.typing import NDArray  # noqa: E402
from photoassistant.recommender import (  # noqa: E402
    DEFAULT_NEIGHBOURS,
    AverageEdit,
    Candidate,
    EvaluationSplit,
    ExpertScales,
    IRecommendationStrategy,
    KMeansGroups,
    MaximalMarginalRelevance,
    PostgresVectorStore,
    RandomCandidates,
    Recommendation,
    Recommender,
    RenderAwareSelection,
    TopCandidates,
    aggregate,
    fingerprints,  # noqa: E402
    score_photograph,
    slice_by,
)
from photoassistant.recommender.metrics import mean_pairwise_distance  # noqa: E402
from photoassistant.recommender.stores import parse_vector  # noqa: E402
from photoassistant.renderer import render, srgb_to_lab  # noqa: E402
from photoassistant.schema import EditRecipe  # noqa: E402
from photoassistant.storage import DatabaseConfig, connect  # noqa: E402

from pipeline import derivative_cache  # noqa: E402
from pipeline.environment import REPOSITORY_ROOT, load  # noqa: E402
from pipeline.make_split import SPLIT_PATH  # noqa: E402

AGREEMENT = REPOSITORY_ROOT / "pipeline/reports/expert_agreement.json"

RESULTS = Path(
    os.environ.get("EVALUATION_DIR") or REPOSITORY_ROOT / "pipeline/reports/evaluation"
)

# Summaries are committed and rows are not, and the split is by directory rather
# than by a field inside one file, so that git can tell them apart at all.
#
# The reason is what each is evidence of. The evaluation split was a random draw:
# lose it and it cannot be recovered, so it lives in the repository. These rows
# follow deterministically from things already committed - the code, the split, the
# frozen expert scales - plus one command, so six megabytes of them in a public
# history buy nothing. They stay on disk, where --re-aggregate still reads them,
# which is the whole point of writing them down (phase 3, decision I).
ROWS = RESULTS / "rows"

RenderFn = Callable[[Candidate], NDArray[np.float64]]


@dataclass(frozen=True)
class Arm:
    """One configuration of the system, named so a report can point at it.

    ``build`` receives the per-photograph rendering function; every arm but the
    two-stage one ignores it.
    """

    name: str
    build: Callable[[RenderFn], IRecommendationStrategy]
    neighbours: int = DEFAULT_NEIGHBOURS
    note: str = ""
    needs_average: bool = False
    is_oracle: bool = False
    # Which ruler this arm measures difference with. ``None`` means the column as
    # phase 2 wrote it; anything else is the fingerprint ablation (task 11).
    fingerprint: str | None = None


def _built_by_the_runner(_: RenderFn) -> IRecommendationStrategy:
    """The average and oracle arms are assembled per photograph, not from here."""
    raise RuntimeError("this arm is built by the runner, not by the registry")


ARMS: dict[str, Arm] = {
    arm.name: arm
    for arm in (
        Arm("top", lambda _: TopCandidates(), note="baseline: nearest, no diversity"),
        Arm(
            "top-per-scene",
            lambda _: TopCandidates(one_per_photograph=True),
            note="baseline: one edit per scene",
        ),
        Arm(
            "top-per-scene-bestfit",
            lambda _: TopCandidates(one_per_photograph=True, prefer_best_fit=True),
            note="one edit per scene, the one schema v1 reproduced best",
        ),
        Arm("random", lambda _: RandomCandidates(seed=20260913), note="floor: three at random"),
        Arm("average", _built_by_the_runner, note="floor: always the average edit",
            needs_average=True),
        Arm("mmr-0.3", lambda _: MaximalMarginalRelevance(lambda_=0.3)),
        Arm("mmr-0.5", lambda _: MaximalMarginalRelevance(lambda_=0.5), note="default (ADR-11)"),
        Arm("mmr-0.7", lambda _: MaximalMarginalRelevance(lambda_=0.7)),
        Arm("kmeans", lambda _: KMeansGroups(), note="three groups, best of each"),
        Arm(
            "mmr-0.5+render6",
            lambda render_fn: RenderAwareSelection(
                MaximalMarginalRelevance(lambda_=0.5), render_fn, finalists=6
            ),
            note="two-stage, ADR-23",
        ),
        Arm("mmr-0.5-k20", lambda _: MaximalMarginalRelevance(lambda_=0.5), neighbours=20),
        Arm("mmr-0.5-k100", lambda _: MaximalMarginalRelevance(lambda_=0.5), neighbours=100),
        Arm(
            "oracle",
            _built_by_the_runner,
            note="CEILING: the photograph's own expert recipes",
            is_oracle=True,
        ),
        # Task 11: the same default strategy, measuring difference with a different
        # ruler. One knob at a time (ADR-10), so everything else stays at default.
        Arm(
            "fp-recipe",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            note="fingerprint: the 13 recipe numbers only",
            fingerprint="recipe",
        ),
        Arm(
            "fp-statistics",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            note="fingerprint: the 17 colour statistics only",
            fingerprint="statistics",
        ),
        Arm(
            "fp-after",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            note="fingerprint: DINOv2 over the edited image - the mandated baseline",
            fingerprint="after-dinov2",
        ),
        Arm(
            "fp-difference",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            note="fingerprint: DINOv2 over the difference image",
            fingerprint="difference-dinov2",
        ),
        Arm(
            "fp-combined+diff",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            note="fingerprint: the thirty hand-made numbers plus the difference encoding",
            fingerprint="combined+difference-dinov2",
        ),
        # k-means with two different rulers, to settle whether the §B77 finding is a
        # property of MMR alone. k-means groups the whole pool before picking, so a
        # different fingerprint can move even the first suggestion — which would make
        # the ablation visible through closeness after all.
        Arm(
            "kmeans-fp-recipe",
            lambda _: KMeansGroups(),
            note="k-means, recipe-only ruler",
            fingerprint="recipe",
        ),
        Arm(
            "kmeans-fp-difference",
            lambda _: KMeansGroups(),
            note="k-means, difference-image ruler",
            fingerprint="difference-dinov2",
        ),
        # The resolution probe. Same hundred questions, same k, the only difference
        # being what the encoder saw: 224 px against the 518 the weights were
        # trained at. A smaller experiment rather than a sample of the data, because
        # a candidate without a vector would decide the comparison by itself.
        Arm(
            "probe-224",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            neighbours=10,
            note="probe: difference image encoded at 224 px",
            fingerprint="difference-dinov2",
        ),
        Arm(
            "probe-518",
            lambda _: MaximalMarginalRelevance(lambda_=0.5),
            neighbours=10,
            note="probe: difference image encoded at 518 px, as trained",
            fingerprint="difference-dinov2-518",
        ),
    )
}

# The fingerprint compositions of task 11. The first three cost nothing — they are
# slices of a vector already in the database — so they run before any encoder pass.
FINGERPRINTS: dict[str, Callable[[], fingerprints.Transform]] = {
    "recipe": lambda: fingerprints.sliced(fingerprints.RECIPE_SLICE),
    "statistics": lambda: fingerprints.sliced(fingerprints.STATISTICS_SLICE),
    "combined": lambda: fingerprints.stored,
}

ARM_VECTORS = REPOSITORY_ROOT / "pipeline/.work/fingerprints"


def fingerprint_transform(name: str | None) -> fingerprints.Transform:
    """Build the ruler for one arm, loading a computed file if it needs one.

    A name with a ``+`` is a concatenation of the parts around it, each block scaled
    so that the widest one does not swallow the rest (§B63) — ``combined+difference
    -dinov2`` is the thirty hand-made numbers next to the 384 neural ones, weighted
    to count comparably rather than 30 against 384.
    """
    if name is None or name == "combined":
        return fingerprints.stored
    if "+" in name:
        return fingerprints.blocks(
            *((fingerprint_transform(part), 1.0) for part in name.split("+"))
        )
    if name in FINGERPRINTS:
        return FINGERPRINTS[name]()

    path = ARM_VECTORS / f"{name}.npz"
    if not path.is_file():
        raise FileNotFoundError(
            f"arm '{name}' needs {path}; run pipeline.embed_arms --arm {name} first"
        )
    return fingerprints.StoredVectors(path)


# Per-process state. Each worker opens its own database connection and reads the
# frozen artefacts once; none of it can be pickled across the boundary anyway.
_STATE: dict[str, object] = {}


def _state() -> dict[str, object]:
    if not _STATE:
        load()
        connection = connect(DatabaseConfig.from_environment())
        _STATE.update(
            connection=connection,
            store=PostgresVectorStore(connection),
            split=EvaluationSplit.load(SPLIT_PATH),
            scales=ExpertScales.load_all(AGREEMENT),
        )
    return _STATE


_TRANSFORMS: dict[str, fingerprints.Transform] = {}


def _transform_for(name: str) -> fingerprints.Transform:
    """One transform per worker process, built once.

    A file-backed composition is tens of megabytes; loading it per photograph would
    cost more than the exam it serves.
    """
    if name not in _TRANSFORMS:
        _TRANSFORMS[name] = fingerprint_transform(name)
    return _TRANSFORMS[name]


def expert_material(connection, reference: str) -> tuple[list[str], list[Candidate]]:
    """The five expert results for one photograph: object keys and their recipes."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.id, e.expert, e.edit, e.after_key, e.style_fingerprint::text
              FROM examples e
              JOIN photos p ON p.id = e.photo_id
             WHERE p.source_reference = %s
               AND NOT e.excluded_from_fitting
               AND e.after_key IS NOT NULL
             ORDER BY e.expert
            """,
            (reference,),
        )
        rows = cursor.fetchall()

    keys = [after_key for _, _, _, after_key, _ in rows]
    recipes = [
        Candidate(
            example_id=str(identifier),
            photo_reference=reference,
            expert=expert,
            recipe=EditRecipe.model_validate(edit),
            fingerprint=parse_vector(fingerprint),
            after_key=after_key,
            photo_distance=0.0,
        )
        for identifier, expert, edit, after_key, fingerprint in rows
    ]
    return keys, recipes


def memoised_renderer(image: NDArray[np.float64]) -> RenderFn:
    """Render a candidate onto this photograph, in Lab, at most once each.

    The two-stage arm renders six finalists and three of them survive; without the
    memo those three would be rendered again for the diversity metric, at 59 ms
    plus 28 ms of conversion apiece.
    """
    cache: dict[str, NDArray[np.float64]] = {}

    def draw(candidate: Candidate) -> NDArray[np.float64]:
        if candidate.example_id not in cache:
            cache[candidate.example_id] = srgb_to_lab(render(image, candidate.recipe))
        return cache[candidate.example_id]

    return draw


def evaluate_one(task: dict) -> dict:
    """One photograph through one arm. Runs in a worker process."""
    reference = task["reference"]
    arm = ARMS[task["arm"]]
    try:
        state = _state()
        scales = state["scales"].get(reference)
        if scales is None:
            return {"reference": reference, "outcome": "skipped", "error": "no expert scales"}

        image = derivative_cache.image(task["pre512_key"])
        draw = memoised_renderer(image)
        keys, recipes = expert_material(state["connection"], reference)

        if arm.is_oracle:
            # The ceiling, and deliberately the one thing the exclusion exists to
            # prevent: this photograph's own expert recipes, handed straight back.
            # No system can do better, and what it scores is the floor of error
            # that fitting leaves behind rather than any failure of retrieval.
            began = time.perf_counter()
            recommendation = Recommendation(
                suggestions=tuple(recipes[:3]), neighbours=(), pool_size=len(recipes)
            )
            seconds = time.perf_counter() - began
            rendered = [draw(candidate) for candidate in recommendation.suggestions]
            expert_labs = [srgb_to_lab(derivative_cache.image(key)) for key in keys]
            score = score_photograph(
                reference, recommendation, rendered, expert_labs, recipes, scales
            )
            return {"outcome": "done", "seconds": seconds, **score.to_dict()}

        if arm.needs_average:
            strategy = AverageEdit(
                Candidate(
                    example_id="average",
                    photo_reference="",
                    expert=None,
                    recipe=EditRecipe.model_validate(task["average_recipe"]),
                    fingerprint=np.zeros(1),
                    after_key=None,
                    photo_distance=0.0,
                )
            )
        else:
            strategy = arm.build(draw)

        store = state["store"]
        if arm.fingerprint:
            store = fingerprints.RestampedStore(store, _transform_for(arm.fingerprint))

        recommender = Recommender(
            embedder=None,  # the vector is already computed; see recommend_from_vector
            store=store,
            strategy=strategy,
            neighbours=arm.neighbours,
        )

        began = time.perf_counter()
        recommendation = recommender.recommend_from_vector(
            np.array(task["vector"], dtype=np.float64),
            exclude=state["split"].held_out_set if task["exclude"] else frozenset(),
        )
        seconds = time.perf_counter() - began

        rendered = [draw(candidate) for candidate in recommendation.suggestions]
        expert_labs = [srgb_to_lab(derivative_cache.image(key)) for key in keys]

        score = score_photograph(
            reference, recommendation, rendered, expert_labs, recipes, scales
        )
        return {"outcome": "done", "seconds": seconds, **score.to_dict()}
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return {
            "reference": reference,
            "outcome": "failed",
            "error": f"{type(error).__name__}: {error}",
        }


@dataclass
class Run:
    arm: str
    rows: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    seconds: float = 0.0


def run_arm(arm: str, tasks: list[dict], workers: int) -> Run:
    print(f"\n{arm}: {len(tasks)} photographs on {workers} workers")
    result = Run(arm=arm)
    began = time.perf_counter()

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(evaluate_one, {**task, "arm": arm}) for task in tasks]
        for finished, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            if row["outcome"] == "done":
                result.rows.append(row)
            elif row["outcome"] == "failed":
                result.failures.append(row)
            if finished % 100 == 0 or finished == len(tasks):
                elapsed = time.perf_counter() - began
                print(f"  {finished}/{len(tasks)}  {elapsed / 60:.1f} min")

    result.seconds = time.perf_counter() - began
    return result


# --------------------------------------------------------------------------- #
# Inputs the run needs before the first photograph
# --------------------------------------------------------------------------- #


def held_out_material(connection, split: EvaluationSplit) -> list[dict]:
    """Each hidden photograph with its neutral image key and its stored vector.

    The vector comes from the column the pipeline filled rather than from the
    encoder: it is the same number, the encoder is fixed for every arm but the one
    that varies it, and re-encoding five hundred photographs fifteen times buys
    nothing. ``--check-vectors`` proves the two agree instead of assuming it.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_reference, pre512_key, clip_embedding::text
              FROM photos
             WHERE source_reference = ANY(%s)
               AND clip_embedding IS NOT NULL
               AND pre512_key IS NOT NULL
             ORDER BY source_reference
            """,
            (list(split.held_out),),
        )
        return [
            {
                "reference": reference,
                "pre512_key": pre512_key,
                "vector": parse_vector(vector).tolist(),
            }
            for reference, pre512_key, vector in cursor.fetchall()
        ]


def average_recipe(connection, split: EvaluationSplit) -> dict:
    """The corpus-average edit, over the build set only.

    Over the build set because a floor must not be allowed to learn from the
    photographs it is judged on — the held-out edits are hidden from this the same
    way they are hidden from the search.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.edit
              FROM examples e
              JOIN photos p ON p.id = e.photo_id
             WHERE NOT e.excluded_from_fitting
               AND NOT (coalesce(p.source_reference, '') = ANY(%s))
            """,
            (sorted(split.held_out),),
        )
        recipes = [EditRecipe.model_validate(edit) for (edit,) in cursor.fetchall()]

    def mean_of(group: str, name: str) -> float:
        return float(np.mean([getattr(getattr(recipe, group), name) for recipe in recipes]))

    return {
        "schema": 1,
        "white_balance": {
            "temperature": mean_of("white_balance", "temperature"),
            "tint": mean_of("white_balance", "tint"),
        },
        "tone": {
            name: mean_of("tone", name)
            for name in ("exposure", "contrast", "highlights", "shadows", "whites", "blacks")
        },
        "color": {name: mean_of("color", name) for name in ("saturation", "vibrance")},
    }


def check_vectors(tasks: list[dict], count: int) -> dict:
    """Encode a few photographs again and compare with what the pipeline stored.

    The control behind the shortcut above. Needs the ``embeddings`` extra; without
    torch installed it says so and returns nothing rather than passing quietly.
    """
    try:
        from photoassistant.recommender import ClipEmbedder
    except ImportError as error:  # pragma: no cover - depends on the extra
        return {"checked": 0, "error": str(error)}

    embedder = ClipEmbedder()
    sample = tasks[:count]
    images = [derivative_cache.image(task["pre512_key"]) for task in sample]
    fresh = embedder.encode(images)

    gaps = [
        float(np.linalg.norm(np.array(task["vector"]) - vector))
        for task, vector in zip(sample, fresh, strict=True)
    ]
    return {
        "checked": len(sample),
        "worst_distance": max(gaps),
        "mean_distance": float(np.mean(gaps)),
    }


# --------------------------------------------------------------------------- #
# Running and reporting
# --------------------------------------------------------------------------- #


def write_arm_report(run: Run, tasks: int, exclude: bool, labels: dict[str, str]) -> dict:
    scores = [row for row in run.rows]
    summary = {
        "arm": run.arm,
        "note": ARMS[run.arm].note if run.arm in ARMS else "",
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "photographs_asked": tasks,
        "exclusion_applied": exclude,
        "seconds": round(run.seconds, 1),
        "seconds_per_photograph": round(run.seconds / max(len(scores), 1), 3),
        "latency": {
            "median": float(np.median([row["seconds"] for row in scores])) if scores else None,
            "p95": float(np.percentile([row["seconds"] for row in scores], 95)) if scores else None,
        },
        **aggregate([_as_score(row) for row in scores]),
        "slices": slice_by([_as_score(row) for row in scores], labels),
        "failures": run.failures,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    ROWS.mkdir(parents=True, exist_ok=True)
    name = run.arm + ("" if exclude else "-no-exclusion")
    (RESULTS / f"{name}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (ROWS / f"{name}.json").write_text(
        json.dumps(scores, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _as_score(row: dict):
    from photoassistant.recommender import PhotographScore

    fields = {
        key: row[key]
        for key in PhotographScore.__dataclass_fields__
        if key in row
    }
    for key in ("suggestions", "experts", "sources"):
        fields[key] = tuple(fields.get(key) or ())
    return PhotographScore(**fields)


def semantic_labels(connection) -> dict[str, str]:
    """One category per photograph, from the catalogue's own subject list.

    Only a fifth of the corpus carries any, and every slice reports its size
    (§B59). The first subject is taken where a photograph has several: a
    photograph that is both "nature" and "animal" would otherwise appear in two
    slices and be counted twice.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_reference, tags::jsonb -> 'subjects' ->> 0
              FROM photos
             WHERE tags::jsonb ? 'subjects'
            """
        )
        return {reference: subject for reference, subject in cursor.fetchall() if subject}


def summary_line(summary: dict) -> str:
    hit = summary.get("hit_rate")
    diversity = summary.get("diversity_ratio", {}).get("median")
    closeness = summary.get("closeness_delta_e", {}).get("median")
    gap = summary.get("diversity_gap", {}).get("median")
    returned = summary.get("suggestions_returned", {}).get("median")

    def show(value, digits=3):
        return "     -" if value is None else f"{value:>6.{digits}f}"

    # The control run carries the same arm name as the real one, so the label says
    # which is which: two lines reading "top-per-scene" with different numbers is
    # exactly the confusion this whole phase is built to avoid.
    label = summary["arm"] + ("" if summary.get("exclusion_applied", True) else " [NO FILTER]")

    return (
        f"{label:<28} hit {show(hit)}   diversity {show(diversity)}   "
        f"closeness {show(closeness, 2)}   gap {show(gap)}   returned {show(returned, 1)}"
    )


EXPERT_FINGERPRINTS_SQL = """
SELECT p.source_reference, e.id, e.style_fingerprint::text
  FROM examples e
  JOIN photos p ON p.id = e.photo_id
 WHERE p.source_reference = ANY(%(references)s)
   AND NOT e.excluded_from_fitting
   AND e.style_fingerprint IS NOT NULL
 ORDER BY p.source_reference, e.expert
"""


def arm_expert_scales(connection, references: list[str], arm: str | None) -> dict[str, float]:
    """How far apart the five experts are **in this arm's fingerprint space**.

    Without this the diversity ratio is nonsense for any arm that changed the
    ruler: the numerator would be measured in 384 unit-normalised dimensions and
    the denominator in the thirty standardised ones from phase 2. Raw figures make
    it obvious — 7,92 against 1,19 — and dividing both by the same 5,05 produces a
    number that looks like a result and is an artefact (§B72 again, one level
    deeper).

    Needs no images: every arm's vectors are already computed, so this is a few
    thousand distances over arrays.
    """
    transform = fingerprint_transform(arm)

    with connection.cursor() as cursor:
        cursor.execute(EXPERT_FINGERPRINTS_SQL, {"references": references})
        rows = cursor.fetchall()

    grouped: dict[str, list[Candidate]] = {}
    for reference, identifier, literal in rows:
        grouped.setdefault(reference, []).append(
            Candidate(
                example_id=str(identifier),
                photo_reference=reference,
                expert=None,
                recipe=None,
                fingerprint=parse_vector(literal),
                after_key=None,
                photo_distance=0.0,
            )
        )

    scales: dict[str, float] = {}
    for reference, candidates in grouped.items():
        vectors = [transform(candidate) for candidate in candidates]
        spread = mean_pairwise_distance(vectors)
        if spread:
            scales[reference] = spread
    return scales


def reaggregate(connection, labels: dict[str, str]) -> list[dict]:
    """Recompute every summary from the rows already on disk.

    The point of keeping per-photograph results (decision I): a new column, a
    different threshold or a fresh slice is a regrouping of what was measured, not
    a second exam. Here it earns itself twice over — the fingerprint ratio was
    being divided by the wrong scale for every arm that changed the ruler, and
    fixing it costs a pass over stored numbers instead of an hour of re-running.
    """
    summaries = []
    scale_cache: dict[str | None, dict[str, float]] = {}

    for path in sorted(RESULTS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        rows_path = ROWS / path.name
        if not rows_path.is_file():
            print(f"  {path.stem}: no stored rows, skipping", file=sys.stderr)
            continue

        rows = json.loads(rows_path.read_text(encoding="utf-8"))

        # Which ruler this arm used decides what its fingerprint diversity can be
        # compared against; see arm_expert_scales.
        arm_name = path.stem.removesuffix("-no-exclusion")
        composition = ARMS[arm_name].fingerprint if arm_name in ARMS else None
        if composition not in scale_cache:
            scale_cache[composition] = arm_expert_scales(
                connection, [row["reference"] for row in rows], composition
            )
        scales = scale_cache[composition]

        for row in rows:
            spread = row.get("diversity_fingerprint")
            scale = scales.get(row["reference"])
            row["fingerprint_ratio"] = spread / scale if spread is not None and scale else None

        scores = [_as_score(row) for row in rows]
        summary = {
            key: value
            for key, value in document.items()
            if key != "slices" and not isinstance(value, dict | list)
        }
        summary.update(
            latency=document.get("latency", {}),
            **aggregate(scores),
            slices=slice_by(scores, labels),
            failures=document.get("failures", []),
        )
        path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        # The rows carry the corrected ratio too, so the next re-aggregation does
        # not have to recompute a scale that has not changed.
        rows_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        summaries.append(summary)
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation over the held-out set.")
    parser.add_argument("--arm", action="append", help="run this arm (repeatable)")
    parser.add_argument("--all", action="store_true", help="run every arm")
    parser.add_argument("--list", action="store_true", help="list the arms and exit")
    parser.add_argument(
        "--re-aggregate",
        action="store_true",
        help="recompute the summaries from the stored per-photograph rows, without rerunning",
    )
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument("--limit", type=int, help="only the first N photographs (a smoke run)")
    parser.add_argument(
        "--no-exclusion",
        action="store_true",
        help=(
            "run without hiding the held-out photographs. The positive control: "
            "the result MUST jump, because each photograph then finds its own edits"
        ),
    )
    parser.add_argument(
        "--check-vectors",
        type=int,
        metavar="N",
        help="re-encode N photographs and compare with the stored vectors (needs torch)",
    )
    arguments = parser.parse_args()

    if arguments.list:
        for arm in ARMS.values():
            print(f"{arm.name:<18} k={arm.neighbours:<4} {arm.note}")
        return 0

    if arguments.re_aggregate:
        load()
        with connect(DatabaseConfig.from_environment()) as connection:
            summaries = reaggregate(connection, semantic_labels(connection))
        for summary in summaries:
            print(summary_line(summary))
        return 0

    chosen = list(ARMS) if arguments.all else (arguments.arm or ["mmr-0.5"])
    unknown = [name for name in chosen if name not in ARMS]
    if unknown:
        print(f"unknown arm(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

    load()
    split = EvaluationSplit.load(SPLIT_PATH)
    if not AGREEMENT.is_file():
        print(
            f"no expert scales at {AGREEMENT}; run pipeline.measure_expert_agreement",
            file=sys.stderr,
        )
        return 1

    with connect(DatabaseConfig.from_environment()) as connection:
        tasks = held_out_material(connection, split)
        labels = semantic_labels(connection)
        average = average_recipe(connection, split) if "average" in chosen else None
        checked = (
            check_vectors(tasks, arguments.check_vectors)
            if arguments.check_vectors
            else None
        )

    if arguments.limit:
        tasks = tasks[: arguments.limit]

    exclude = not arguments.no_exclusion
    prepared = [
        {**task, "exclude": exclude, "average_recipe": average}
        for task in tasks
    ]

    print(f"photographs {len(prepared)}   exclusion {'on' if exclude else 'OFF (control)'}")
    if checked:
        print(f"vector check: {checked}")

    summaries = []
    failures = 0
    for name in chosen:
        run = run_arm(name, prepared, arguments.workers)
        summary = write_arm_report(run, len(prepared), exclude, labels)
        summaries.append(summary)
        failures += len(run.failures)
        print("  " + summary_line(summary))

    print("\n" + "-" * 96)
    for summary in summaries:
        print(summary_line(summary))
    print(f"\nwritten to {RESULTS}")

    if failures:
        print(f"\nFAILED on {failures} photograph runs", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
