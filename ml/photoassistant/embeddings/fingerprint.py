"""The style fingerprint: thirty numbers describing one expert edit.

Two halves, answering two different questions (``docs/notes`` §B38):

``recipe`` (13 numbers)
    What the expert **set** — the ten sliders in the order the optimiser uses,
    plus three samples of the master tone curve. The cause.

``statistics`` (17 numbers)
    What that **did** to the image — the difference in colour statistics between
    the neutral rendition and the expert's result. The effect. See
    ``statistics.py``.

Both are needed: the same recipe does not have the same effect on every
photograph, so the first half alone cannot say what a suggestion will look like,
and the second alone cannot say how to reproduce it.

**Why no neural model here.** The composition is deliberately the plain one. A
review in phase 1 established that an embedding of the *edited* image mostly
encodes the scene rather than the edit, and the remaining candidates are an
ablation axis for phase 3, not a phase 2 decision (``docs/STATUS.md``).
Recomputing a fingerprint is minutes, so nothing is locked in by starting here.

**The dimension is a contract.** A migration fixes ``examples.style_fingerprint``
to ``vector(30)``; changing the composition means a new migration and a full
recomputation, which is affordable but not free.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self

import numpy as np
from numpy.typing import NDArray

from photoassistant.embeddings.statistics import STATISTIC_COUNT, STATISTIC_NAMES
from photoassistant.fitting.least_squares import CURVE_X, SCALARS
from photoassistant.renderer.curve import evaluate, tangents
from photoassistant.schema import EditRecipe

# The recipe half. Ten sliders plus one sample of the curve per interior control
# point — the same three positions the fit searches, so the two descriptions of a
# curve line up instead of being two conventions for the same thing.
RECIPE_COMPONENT_COUNT: Final[int] = len(SCALARS) + len(CURVE_X)

FINGERPRINT_DIMENSION: Final[int] = RECIPE_COMPONENT_COUNT + STATISTIC_COUNT

COMPONENT_NAMES: Final[tuple[str, ...]] = (
    *(name for _, name, _ in SCALARS),
    *(f"curve_at_{x:g}" for x in CURVE_X),
    *STATISTIC_NAMES,
)

assert len(COMPONENT_NAMES) == FINGERPRINT_DIMENSION


def recipe_components(recipe: EditRecipe) -> NDArray[np.float64]:
    """The thirteen recipe numbers, in ``COMPONENT_NAMES`` order.

    Sliders are divided by their own limit, so exposure in stops and contrast in
    its own scale arrive on the same footing — the same normalisation the
    optimiser searches in.

    The curve is sampled rather than copied. Its control points are not the same
    from recipe to recipe: a fit with the curve enabled produces three interior
    points, the analytic starting point produces one, and a neutral recipe none.
    Reading the **curve's value** at three fixed inputs describes all of them in
    the same terms. What is stored is the deviation from the diagonal, so a
    neutral curve contributes zeros rather than 0.25, 0.5, 0.75.
    """
    sliders = [
        getattr(getattr(recipe, group), name) / limit for group, name, limit in SCALARS
    ]

    points = np.array(recipe.tone_curve.points, dtype=np.float64)
    x = np.array(CURVE_X, dtype=np.float64)
    # Clipped exactly as the renderer clips its lookup table (§6.3), so the
    # fingerprint describes the curve that actually gets applied.
    y = np.clip(evaluate(points, tangents(points), x), 0.0, 1.0)

    return np.array([*sliders, *(y - x)], dtype=np.float64)


def raw_fingerprint(
    recipe: EditRecipe, statistics_difference: NDArray[np.floating]
) -> NDArray[np.float64]:
    """Assemble the thirty numbers, before scaling.

    "Raw" matters: the two halves are in incompatible units at this point, so a
    distance between two raw fingerprints is not meaningful. Only
    ``Scaling.apply`` produces a vector that may be compared (§B43).
    """
    difference = np.asarray(statistics_difference, dtype=np.float64)
    if difference.shape != (STATISTIC_COUNT,):
        raise ValueError(
            f"expected {STATISTIC_COUNT} statistics, got shape {difference.shape}"
        )
    return np.concatenate([recipe_components(recipe), difference])


@dataclass(frozen=True)
class Scaling:
    """Per-component mean and standard deviation, measured once over the corpus.

    Why this exists at all: the recipe half runs over roughly -1 to 1 while the
    statistics half runs over tens of L* units. Summed as they are, "how different
    are these two edits" would mostly measure the change in brightness, because
    that component has the widest numeric range — a question nobody asked (§B43).

    **These constants are frozen and committed.** Every vector in the column must
    have been built with the same ones; a column holding two generations of
    constants is not an error anything reports, the distances simply stop meaning
    what they are read to mean.
    """

    mean: NDArray[np.float64]
    deviation: NDArray[np.float64]

    def __post_init__(self) -> None:
        for name, values in (("mean", self.mean), ("deviation", self.deviation)):
            if values.shape != (FINGERPRINT_DIMENSION,):
                raise ValueError(f"{name} must have {FINGERPRINT_DIMENSION} entries")

    def apply(self, raw: NDArray[np.floating]) -> NDArray[np.float64]:
        """Centre and scale one raw fingerprint into the comparable space."""
        vector = np.asarray(raw, dtype=np.float64)
        if vector.shape != (FINGERPRINT_DIMENSION,):
            raise ValueError(f"expected {FINGERPRINT_DIMENSION} components")
        return (vector - self.mean) / self.deviation

    @classmethod
    def fit(cls, raw: NDArray[np.floating]) -> Self:
        """Measure the constants from a stack of raw fingerprints, one per row.

        A component that never varies gets a deviation of one rather than zero.
        Dividing by its true zero would produce infinities; leaving it at one
        makes it contribute exactly nothing to every distance, which is the honest
        reading of a number that is the same everywhere.
        """
        stack = np.atleast_2d(np.asarray(raw, dtype=np.float64))
        if stack.shape[1] != FINGERPRINT_DIMENSION:
            raise ValueError(f"expected rows of {FINGERPRINT_DIMENSION} components")

        deviation = stack.std(axis=0)
        deviation[deviation == 0.0] = 1.0
        return cls(mean=stack.mean(axis=0), deviation=deviation)

    def to_dict(self, **metadata: Any) -> dict[str, Any]:
        """A JSON-ready document, component names included so it can be read.

        The names are not used when loading — the order is the contract — but a
        constants file nobody can inspect is a constants file nobody checks.
        """
        return {
            **metadata,
            "dimension": FINGERPRINT_DIMENSION,
            "components": list(COMPONENT_NAMES),
            "mean": [float(value) for value in self.mean],
            "deviation": [float(value) for value in self.deviation],
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> Self:
        stored = document.get("dimension")
        if stored != FINGERPRINT_DIMENSION:
            raise ValueError(
                f"scaling was measured for dimension {stored}, but this build "
                f"produces {FINGERPRINT_DIMENSION}. Recompute the constants and "
                f"every fingerprint together — a column may not hold both."
            )
        return cls(
            mean=np.array(document["mean"], dtype=np.float64),
            deviation=np.array(document["deviation"], dtype=np.float64),
        )

    @classmethod
    def load(cls, path: Path) -> Self:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path, **metadata: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(**metadata), indent=2) + "\n", encoding="utf-8"
        )
