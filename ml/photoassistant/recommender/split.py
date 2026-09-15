"""The evaluation split: which photographs the recommender is not allowed to see.

The database holds a real expert edit for **every** photograph it contains. Ask it
about a photograph that is in there and it finds that very photograph as the most
similar scene and hands back what the expert did to it — a perfect score measuring
lookup rather than recommendation (``docs/notes/phase-2-concepts.md`` §B39).

So 500 photographs are held out. **Held out means filtered, not deleted**: the rows
stay where they are and every retrieval query excludes them (phase 3, decision A).
Nothing in the database is destroyed to run an experiment.

**The file is the authority, not the algorithm.** ``pipeline/make_split.py`` draws
the sample once, writes it to
``pipeline/reports/evaluation_split.json``, and from then on that file decides what
is hidden. Re-deriving the sample from the seed on every run would tie the meaning
of "held out" to the exact behaviour of ``random.sample`` in whichever Python
happens to be installed, and a split that quietly changes between two runs makes
every number produced before it wrong.

The same reasoning as ``pipeline/probe/sample.json`` in phase 1: a measurement
whose input cannot be reproduced is not a measurement.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self

# Plan §8: 4.500 photographs stay visible, 500 are hidden.
HELD_OUT_COUNT: Final[int] = 500


class SplitError(RuntimeError):
    """The split file is missing, malformed, or no longer describes this corpus."""


@dataclass(frozen=True)
class EvaluationSplit:
    """The held-out photographs, plus what was known when they were drawn.

    ``held_out`` carries **source references** (``a0001-jmac_DSC1459``), not row
    identifiers. References are readable, they survive rebuilding the database
    from the dataset, and a human can check one against the catalogue; a UUID can
    do none of those things.

    ``drawn_from`` is the number of photographs that were eligible at the time.
    It is kept so that the split can notice it has gone stale: if the corpus grows
    or shrinks, the *complement* of this list silently becomes a different build
    set, and every metric computed after that means something else.
    """

    seed: int
    created_at: str
    drawn_from: int
    held_out: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.held_out:
            raise SplitError("split is empty")
        if len(set(self.held_out)) != len(self.held_out):
            raise SplitError("split contains the same reference twice")
        if self.drawn_from < len(self.held_out):
            raise SplitError(
                f"drawn_from ({self.drawn_from}) is smaller than the sample "
                f"({len(self.held_out)})"
            )

    @property
    def held_out_set(self) -> frozenset[str]:
        """The same references as a set, for membership tests."""
        return frozenset(self.held_out)

    def is_held_out(self, reference: str) -> bool:
        return reference in self.held_out_set

    def build_set(self, references: list[str]) -> list[str]:
        """Everything in ``references`` that is not hidden, order preserved."""
        hidden = self.held_out_set
        return [reference for reference in references if reference not in hidden]

    # -- persistence ----------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        try:
            return cls(
                seed=int(payload["seed"]),
                created_at=str(payload["created_at"]),
                drawn_from=int(payload["drawn_from"]),
                held_out=tuple(payload["held_out"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SplitError(f"split file is malformed: {error}") from error

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "created_at": self.created_at,
            "drawn_from": self.drawn_from,
            "held_out_count": len(self.held_out),
            "held_out": list(self.held_out),
        }

    @classmethod
    def load(cls, path: Path) -> Self:
        if not path.is_file():
            raise SplitError(
                f"no evaluation split at {path}. Run pipeline.make_split first — "
                "the split is drawn once and then read, never re-derived."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SplitError(f"split file is not valid JSON: {error}") from error
        return cls.from_dict(payload)

    def save(self, path: Path) -> None:
        """Write the split. Sorted, indented, newline-terminated — it is read by people.

        Refusing to overwrite is the caller's job, not this method's: the check
        belongs where the intent is known (``make_split --force``).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
