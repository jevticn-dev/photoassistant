"""The starting points must actually reach the optimiser.

This file exists because they once did not. The second fitting pass was configured
with six neutral offsets instead of two by assigning to
``photoassistant.fitting.STARTS`` — a name re-exported by the package, while
``fit`` reads the one bound inside ``least_squares``. The assignment landed on the
wrong binding and did nothing, and the pass spent two hours reporting that six
starting points made no difference to any of 775 edits.

Nothing failed. No test went red. The only visible trace was a number that looked
like a result: "replaced 0, mean gain 0.000". A setting that silently fails to
apply and a setting that applied and did not help print exactly the same thing —
one is a bug, the other a finding (notes §B50).

So the fix is not only that ``starts`` is now an argument. It is that the argument
has an **observable consequence** something can assert. ``FitResult.iterations``
sums the function evaluations over every attempt, so more starting points must
cost strictly more evaluations. That is the positive control: proof that the
treatment was administered, checked before anyone reads the outcome.
"""

import numpy as np
import pytest

from photoassistant.fitting import STARTS, fit
from photoassistant.renderer import render
from photoassistant.schema import EditRecipe

# Small and cheap: this measures how many attempts run, not how well they land.
SIZE = 16
EVALUATIONS = 12


@pytest.fixture(scope="module")
def pair() -> tuple[np.ndarray, np.ndarray]:
    """A gradient and a visibly edited version of it."""
    ramp = np.linspace(0.05, 0.95, SIZE, dtype=np.float32)
    before = np.stack(
        [
            np.tile(ramp, (SIZE, 1)),
            np.tile(ramp[::-1], (SIZE, 1)),
            np.tile(ramp, (SIZE, 1)) * 0.6 + 0.2,
        ],
        axis=-1,
    )
    recipe = EditRecipe.model_validate(
        {"schema": 1, "tone": {"exposure": 0.6, "contrast": 25.0}, "color": {"saturation": 15.0}}
    )
    return before, render(before, recipe)


def run(pair: tuple[np.ndarray, np.ndarray], starts) -> int:
    before, after = pair
    return fit(
        before, after, starts=starts, stride=1, max_evaluations=EVALUATIONS
    ).iterations


def test_more_starting_points_actually_reach_the_optimiser(pair) -> None:
    """The positive control. Without this, "no effect" cannot be trusted."""
    one = run(pair, (0.05,))
    six = run(pair, (0.05, -0.05, 0.3, -0.3, 0.6, -0.6))

    assert one > 0
    assert six > one, (
        "six starting points cost no more evaluations than one, so they never "
        "reached the search — the exact failure that made a two-hour pass report "
        "a result it had not measured"
    )


def test_the_default_is_used_when_no_starts_are_given(pair) -> None:
    """Passing the default explicitly must be the same as not passing it.

    Guards the other direction: a caller that says nothing keeps the library's
    two offsets rather than silently getting one, or none.
    """
    assert run(pair, None) == run(pair, STARTS)


def test_a_single_explicit_start_is_cheaper_than_the_default_two(pair) -> None:
    """Confirms the count is what varies, not something incidental to the images."""
    assert run(pair, (0.05,)) < run(pair, None)
