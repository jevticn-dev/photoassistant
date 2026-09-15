"""Where a candidate's fingerprint comes from — the axis of the phase 3 ablation.

The fingerprint is the **ruler** by which two edits are called different, and every
strategy that spreads its suggestions reads it. Nothing says the thirty numbers
phase 2 chose are the right ruler; that is what gets measured here (§B39).

Six compositions, and they cost wildly different amounts to produce:

``recipe``        the 13 numbers of the fitted recipe — **a slice of what is stored**
``statistics``    the 17 colour-statistics numbers — likewise a slice
``combined``      both, which is what the database column already holds
``after``         an encoder over the edited image — the baseline the mentor's
                  review predicted would mostly describe the scene
``difference``    an encoder over ``after − before``, which keeps *where* the edit
                  changed something (§B62)
``combined+diff`` the hand-made numbers concatenated with that encoding (§B63)

**The first three are free.** They are columns 0..12 and 13..29 of a vector already
in the database, so two of the six arms need no model, no pass over 25.000 images
and no new file. Running those first is not a shortcut — it is the cheapest
information in the study, and it tells us how much of the answer the expensive arms
even have left to explain.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from photoassistant.embeddings.fingerprint import RECIPE_COMPONENT_COUNT
from photoassistant.recommender.interfaces import Candidate

# Where the recipe half ends and the statistics half begins, in the stored vector.
RECIPE_SLICE: Final[slice] = slice(0, RECIPE_COMPONENT_COUNT)
STATISTICS_SLICE: Final[slice] = slice(RECIPE_COMPONENT_COUNT, None)

Transform = Callable[[Candidate], NDArray[np.float64]]


def stored(candidate: Candidate) -> NDArray[np.float64]:
    """The column as written in phase 2: recipe ⊕ statistics, thirty numbers."""
    return candidate.fingerprint


def sliced(part: slice) -> Transform:
    """One half of the stored vector, free of charge."""

    def take(candidate: Candidate) -> NDArray[np.float64]:
        return candidate.fingerprint[part]

    return take


def blocks(*parts: tuple[Transform, float]) -> Transform:
    """Concatenate several fingerprints, each block scaled by its own weight.

    Concatenation is not neutral: distance in the joined space is a sum over
    components, so a block of 384 neural numbers would carry about 93% of every
    distance and a block of 13 recipe numbers under 4% — the "combination" would be
    the neural arm wearing a hat (§B63).

    Each block is therefore scaled to **unit length** before being weighted, so
    that it contributes according to its weight and not according to how wide it
    is or how its numbers happen to be scaled.

    **Dividing by the square root of the width is not enough, and the first version
    here did exactly that.** It assumes every block has unit variance per component,
    which is true of the z-scored thirty (norm about 5,5) and false of an
    L2-normalised neural block (norm exactly 1). The neural side came out twenty
    times too small, contributed nothing, and the "combination" arm reproduced the
    plain one to every decimal — a result that looked like a finding and was an
    erased term. Caught because two arms agreed too perfectly (§B50).

    The weights are an explicit argument because they are part of what the arm
    *is*: the same composition with a different balance is a different experiment.
    """

    def join(candidate: Candidate) -> NDArray[np.float64]:
        pieces = []
        for transform, weight in parts:
            block = np.asarray(transform(candidate), dtype=np.float64)
            norm = float(np.linalg.norm(block))
            pieces.append(block * (weight / norm) if norm > 0.0 else block)
        return np.concatenate(pieces)

    return join


class StoredVectors:
    """Fingerprints computed offline, keyed by example id.

    Written by ``pipeline.embed_arms`` into a ``.npz`` beside the cache rather than
    into the database: an arm with 384 numbers does not fit a ``vector(30)`` column,
    and the column only changes if an arm wins — together with its scaling
    constants, never one without the other (phase 3, decision D).
    """

    def __init__(self, path: Path) -> None:
        payload = np.load(path, allow_pickle=False)
        self.identifiers = [str(value) for value in payload["identifiers"]]
        self.vectors = payload["vectors"].astype(np.float64)
        self._index = {identifier: row for row, identifier in enumerate(self.identifiers)}

    @property
    def dimension(self) -> int:
        return int(self.vectors.shape[1])

    def __len__(self) -> int:
        return len(self.identifiers)

    def __call__(self, candidate: Candidate) -> NDArray[np.float64]:
        row = self._index.get(candidate.example_id)
        if row is None:
            # A candidate with no vector in this arm would otherwise be compared
            # against zeros and look maximally different from everything, which is
            # the most flattering possible failure. Refuse instead.
            raise KeyError(f"no fingerprint for example {candidate.example_id} in this arm")
        return self.vectors[row]


def apply(transform: Transform, candidates: list[Candidate]) -> list[Candidate]:
    """Re-stamp a pool with the fingerprints of one arm, leaving everything else."""
    return [replace(candidate, fingerprint=transform(candidate)) for candidate in candidates]


class RestampedStore:
    """An ``IVectorStore`` that hands back pools measured with another ruler.

    The ablation changes **one** thing — what "different" means — and nothing else:
    the same query vector, the same neighbours, the same candidates, in the same
    order. Wrapping the store rather than teaching the recommender about arms keeps
    that guarantee visible, and makes each composition another implementation of an
    interface that already exists rather than a branch inside the online path.
    """

    def __init__(self, inner, transform: Transform) -> None:
        self._inner = inner
        self._transform = transform

    def neighbours(self, vector, *, count: int, exclude: frozenset[str]):
        return self._inner.neighbours(vector, count=count, exclude=exclude)

    def candidates(self, neighbours) -> list[Candidate]:
        return apply(self._transform, self._inner.candidates(neighbours))
