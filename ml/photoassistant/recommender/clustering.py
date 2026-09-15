"""k-means over style fingerprints, written out rather than imported.

Thirty lines of NumPy against a dependency that would arrive with a compiler
toolchain and a release cadence of its own — for a routine this project needs in
exactly one place, on pools of a few hundred points with three groups. The whole
run is microseconds, so nothing here is worth tuning.

**Deterministic by construction.** Every experiment is run again when a knob
changes, and two runs of the same configuration that disagree would make every
comparison meaningless. The seed is an argument, initialisation is k-means++ with
that seed, and ties are broken by index rather than by whatever order the array
happened to be in.
"""

import numpy as np
from numpy.typing import NDArray

# Lloyd's algorithm converges quickly at this size; the cap is a guard against a
# pathological input, not a tuning knob. Convergence is detected exactly — labels
# stop moving — so the cap is rarely reached.
MAX_ITERATIONS = 50


def _initial_centres(
    points: NDArray[np.float64], k: int, generator: np.random.Generator
) -> NDArray[np.float64]:
    """k-means++: first centre at random, each next one far from those chosen.

    Plain random initialisation regularly puts two centres inside the same dense
    clump, and Lloyd's algorithm cannot recover from that — it converges happily
    to a split nobody would call three groups. k-means++ spreads the start by
    drawing each next centre with probability proportional to its squared distance
    from the nearest centre so far.
    """
    centres = [points[generator.integers(len(points))]]

    for _ in range(1, k):
        squared = np.min(
            np.array([np.sum((points - centre) ** 2, axis=1) for centre in centres]),
            axis=0,
        )
        total = squared.sum()
        if total <= 0.0:
            # Every remaining point coincides with a centre; spreading further is
            # impossible and any choice is as good as another.
            centres.append(points[generator.integers(len(points))])
            continue
        centres.append(points[generator.choice(len(points), p=squared / total)])

    return np.array(centres, dtype=np.float64)


def kmeans(points: NDArray[np.floating], k: int, *, seed: int) -> NDArray[np.int_]:
    """Group ``points`` into at most ``k`` clusters; returns one label per point.

    "At most" is deliberate. With fewer points than groups, or with duplicates
    where distinct values were expected, the honest answer is fewer clusters — an
    empty group padded into existence would make the caller believe it had three
    kinds of thing when it had two.
    """
    stack = np.atleast_2d(np.asarray(points, dtype=np.float64))
    if k <= 0 or len(stack) == 0:
        return np.zeros(0, dtype=np.int_)
    if len(stack) <= k:
        return np.arange(len(stack), dtype=np.int_)

    generator = np.random.default_rng(seed)
    centres = _initial_centres(stack, k, generator)
    labels = np.zeros(len(stack), dtype=np.int_)

    for _ in range(MAX_ITERATIONS):
        distances = np.array([np.sum((stack - centre) ** 2, axis=1) for centre in centres])
        updated = np.argmin(distances, axis=0)
        if np.array_equal(updated, labels):
            break
        labels = updated

        for index in range(len(centres)):
            members = stack[labels == index]
            if len(members):
                centres[index] = members.mean(axis=0)
            else:
                # An emptied cluster is re-seeded onto the point that fits worst
                # anywhere, which is where another group is most plausibly hiding.
                # Dropping it instead would silently return k-1 groups.
                centres[index] = stack[int(np.argmax(np.min(distances, axis=0)))]

    return labels
