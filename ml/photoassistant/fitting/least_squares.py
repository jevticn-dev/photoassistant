"""Recover our parameters from a before/after pair (plan §4.3).

The idea is not to translate somebody else's parameters into ours, which would be
guesswork about a format nobody documented. It is to **reconstruct the result**:
find the values of *our* parameters that, run through *our* renderer over the
"before" image, land closest to the expert's "after".

What is being searched for is only the eleven values. The formulas are fixed by
``RENDERER_SPEC.md`` and never move — that is what makes a fitted recipe mean the
same thing forever.

Two deliberate choices worth knowing:

* **The objective is ΔE, not RGB distance.** Optimising an RGB difference would
  spend effort where the eye does not look. ΔE costs more per evaluation, which
  the subsample below pays for.
* **The fit runs on a subsample of pixels.** Eleven global parameters cannot see
  individual pixels; a regular stride carries the same information for a fraction
  of the work. The error that gets *reported* is always measured on the full
  image, never on the subsample.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares

from photoassistant.renderer.color import delta_e
from photoassistant.renderer.pipeline import render
from photoassistant.schema import EditRecipe

# The ten scalars, in the order the parameter vector uses. The tone curve is not
# among them: it is fitted separately, so that "how far do the sliders alone
# get us" and "how much does the master curve add" stay separate numbers. Plan
# §4.2 claims the curve absorbs most of the remainder — this keeps that claim
# testable rather than assumed.
SCALARS: tuple[tuple[str, str, float], ...] = (
    ("white_balance", "temperature", 100.0),
    ("white_balance", "tint", 100.0),
    ("tone", "exposure", 5.0),
    ("tone", "contrast", 100.0),
    ("tone", "highlights", 100.0),
    ("tone", "shadows", 100.0),
    ("tone", "whites", 100.0),
    ("tone", "blacks", 100.0),
    ("color", "saturation", 100.0),
    ("color", "vibrance", 100.0),
)


@dataclass(frozen=True)
class FitResult:
    """One fitted recipe and how well it did, measured on the full image."""

    recipe: EditRecipe
    mean_delta_e: float
    median_delta_e: float
    max_delta_e: float
    iterations: int
    seconds: float
    converged: bool

    def at_bounds(self, tolerance: float = 0.02) -> list[str]:
        """Parameters sitting on the edge of their range.

        A value pinned at ±100 does not mean the edit was extreme; it usually
        means the parameter's scale is too weak to express what the expert did,
        and the optimiser pushed it as far as it would go. Counting these across
        the sample is how phase 1b judges the constants in ``RENDERER_SPEC.md``
        §8.3 — see ADR-16.
        """
        pinned = []
        for group, name, limit in SCALARS:
            value = getattr(getattr(self.recipe, group), name)
            if abs(abs(value) - limit) <= tolerance * limit:
                pinned.append(name)
        return pinned


# Interior control points of the fitted tone curve. x is fixed and only y is
# searched for: letting x move would let two points swap and the schema forbids
# that (RENDERER_SPEC.md §6.1), and three evenly spaced points already give the
# curve its S, its lift and its shoulder.
CURVE_X: tuple[float, ...] = (0.25, 0.5, 0.75)

# Identity in the parameterisation below — the value of each fraction that
# reproduces the diagonal.
CURVE_NEUTRAL: tuple[float, ...] = (0.25, 1.0 / 3.0, 0.5)


def curve_points(fractions: NDArray[np.float64]) -> list[tuple[float, float]]:
    """Three fractions in [0, 1] to a monotone set of control points.

    Each fraction says how far up the *remaining* room the next point sits, so
    ``0 <= y1 <= y2 <= y3 <= 1`` holds by construction rather than by a penalty
    the optimiser has to learn. A non-monotone curve would invert gradients and
    show as banding, so it must be unreachable, not merely discouraged.
    """
    y: list[float] = []
    previous = 0.0
    for fraction in np.clip(fractions, 0.0, 1.0):
        previous = previous + (1.0 - previous) * float(fraction)
        y.append(previous)
    return [(0.0, 0.0), *zip(CURVE_X, y, strict=True), (1.0, 1.0)]


def recipe_from_vector(vector: NDArray[np.float64]) -> EditRecipe:
    """Normalised vector in [-1, 1] back to a recipe.

    The optimiser works in normalised units so that one step means the same
    amount of change for exposure, in stops, as for contrast, in its own scale.
    Feeding it the raw values would make it crawl along exposure and leap along
    everything else.
    """
    groups: dict[str, dict[str, float]] = {"white_balance": {}, "tone": {}, "color": {}}
    for value, (group, name, limit) in zip(vector[: len(SCALARS)], SCALARS, strict=True):
        groups[group][name] = float(np.clip(value, -1.0, 1.0) * limit)

    document: dict[str, object] = {"schema": 1, **groups}
    if len(vector) > len(SCALARS):
        document["tone_curve"] = {"points": curve_points(vector[len(SCALARS) :])}
    return EditRecipe.model_validate(document)


def vector_from_recipe(recipe: EditRecipe) -> NDArray[np.float64]:
    return np.array(
        [getattr(getattr(recipe, group), name) / limit for group, name, limit in SCALARS],
        dtype=np.float64,
    )


def measure(
    rendered: NDArray[np.floating], target: NDArray[np.floating]
) -> tuple[float, float, float]:
    """Mean, median and maximum ΔE over every pixel."""
    difference = delta_e(rendered, target)
    return (
        float(difference.mean()),
        float(np.median(difference)),
        float(difference.max()),
    )


# Where the searches begin, in normalised units.
#
# **Never the origin.** `least_squares` with the default `trf` sets its initial
# trust-region radius from the norm of the starting point, so starting at exactly
# zero leaves it with nothing to step by: it computes one Jacobian, takes a
# vanishing step and stops on `xtol` having improved nothing. Measured on
# a0101-kme_610 — from zero it returns the input untouched at ΔE 7.02, from a
# small offset it reaches 1.84.
#
# Two starts rather than one because the problem **has local minima**: the same
# image reached 1.81, 2.01 and 4.59 from three different starting points. The
# probe is asking what the renderer *can* do, so the best of several attempts is
# the honest answer; a single arbitrary start would report whichever basin it
# happened to land in.
#
# Phase 2 adds the catalogue's analytic mapping as a further start, through
# `extra_starts`, rather than replacing these. Measured on the probe: as the
# *only* start the mapping is worse than a neutral offset (2.18 against 1.77),
# because a half-right guess leaves the search in the wrong valley. As an
# *additional* one, where the best of several wins, it is worth about 1%.
STARTS: tuple[float, ...] = (0.05, -0.05)


def fit(
    before: NDArray[np.floating],
    after: NDArray[np.floating],
    *,
    start: EditRecipe | None = None,
    extra_starts: Sequence[EditRecipe] = (),
    with_curve: bool = False,
    stride: int = 4,
    max_evaluations: int = 400,
    diff_step: float = 3e-3,
) -> FitResult:
    """Search for the recipe that best reproduces ``after`` from ``before``.

    With ``start`` given, that single point is used and nothing else — a way to
    ask "how far does this particular guess get", which is how the probe compared
    the analytic mapping against fitting.

    Otherwise the search runs from every offset in ``STARTS`` **plus** every
    recipe in ``extra_starts``, and the best result wins. More starts cost
    proportionally more time and buy insurance against local minima, which this
    problem has: the same photograph reached 1.81, 2.01 and 4.59 from three
    different starting points (notes §B8).

    ``with_curve`` adds the three interior control points of the master curve to
    the search. Running both ways is how plan §4.2's claim — that the curve
    absorbs most of what the sliders cannot reach — gets tested instead of
    assumed.

    Reported error is always measured on the **full** image, never on the
    subsample the search runs over.
    """
    small_before = np.asarray(before, dtype=np.float32)[::stride, ::stride]
    small_after = np.asarray(after, dtype=np.float32)[::stride, ::stride]

    def residuals(vector: NDArray[np.float64]) -> NDArray[np.float64]:
        rendered = render(small_before, recipe_from_vector(vector))
        # least_squares minimises the sum of squares, so handing it per-pixel ΔE
        # minimises the sum of squared ΔE — close enough to the mean, and it lets
        # the optimiser see where the error lives instead of one flat number.
        return delta_e(rendered, small_after).ravel()

    tail = np.array(CURVE_NEUTRAL) if with_curve else np.array([])
    width = len(SCALARS) + len(tail)

    if start is not None:
        initials = [np.concatenate([vector_from_recipe(start), tail])]
    else:
        initials = [np.concatenate([np.full(len(SCALARS), offset), tail]) for offset in STARTS]
        initials.extend(
            np.concatenate([vector_from_recipe(recipe), tail]) for recipe in extra_starts
        )

    # The curve fractions live in [0, 1]; the scalars in [-1, 1].
    lower = np.concatenate([-np.ones(len(SCALARS)), np.zeros(len(tail))])
    upper = np.ones(width)

    began = time.perf_counter()
    attempts = []
    for initial in initials:
        solution = least_squares(
            residuals,
            initial,
            bounds=(lower, upper),
            max_nfev=max_evaluations,
            # The renderer is not differentiable in closed form, so the Jacobian
            # is numerical, and how far each parameter is nudged to estimate it
            # matters more than anything else measured in phase 2.
            #
            # The probe chose 1e-2 and warned that anything smaller would vanish
            # into float32 rounding inside the renderer, leaving the direction
            # reading as flat. Measured over the 50 hardest fits, that warning was
            # caution turned into a limit: at 3e-3 the search lands better on 41
            # of 50 and worse on 4, and at 3e-2 it is worse on 45 of 50. Below
            # 3e-3 the gain flattens while the cost keeps rising (1e-3 and 3e-4
            # buy 0.007 and 0.016 dE for 30% and 13% more time).
            diff_step=diff_step,
        )
        attempts.append(solution)
    elapsed = time.perf_counter() - began

    best = min(attempts, key=lambda solution: float(np.mean(residuals(solution.x))))
    recipe = recipe_from_vector(best.x)
    mean, median, worst = measure(render(before, recipe), after)

    return FitResult(
        recipe=recipe,
        mean_delta_e=mean,
        median_delta_e=median,
        max_delta_e=worst,
        iterations=sum(int(solution.nfev) for solution in attempts),
        seconds=elapsed,
        converged=any(bool(solution.success) for solution in attempts),
    )
