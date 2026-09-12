"""Embeddings — vector descriptions of content and of style.

Two different things, answering two different questions.

``clip_embedding`` (content of the "before" image)
    CLIP ViT-B/32, 512 dimensions, L2-normalised. Answers "what did experts do to
    scenes like this one". Written to ``photos.clip_embedding``, which carries the
    HNSW index because that is where a search actually happens.

``style_fingerprint`` (what the expert did)
    Thirty numbers: the fitted recipe, plus the difference in colour statistics
    between the neutral rendition and the expert's result. No neural model — the
    remaining candidates are an ablation axis for phase 3 (``docs/STATUS.md``).
    Written to ``examples.style_fingerprint`` and later ``looks``. **No index**:
    it is used to compare a few dozen already-retrieved candidates, and an index
    speeds up finding among many, not comparing among few (``docs/notes`` §B40).

**Nothing here imports torch, and that is deliberate.** ``clip`` is the only
module that needs it, it imports it lazily, and this file does not import
``clip``. So ``import photoassistant.embeddings`` works in an installation
without the ``embeddings`` extra — the ordinary test run and CI — and the extra
stays a genuine boundary rather than a habit. Reach the encoder explicitly:

    from photoassistant.embeddings.clip import ClipEncoder
"""

from photoassistant.embeddings.fingerprint import (
    COMPONENT_NAMES,
    FINGERPRINT_DIMENSION,
    RECIPE_COMPONENT_COUNT,
    Scaling,
    raw_fingerprint,
    recipe_components,
)
from photoassistant.embeddings.statistics import (
    STATISTIC_COUNT,
    STATISTIC_NAMES,
    colour_statistics,
    statistics_difference,
)

__all__ = [
    "COMPONENT_NAMES",
    "FINGERPRINT_DIMENSION",
    "RECIPE_COMPONENT_COUNT",
    "STATISTIC_COUNT",
    "STATISTIC_NAMES",
    "Scaling",
    "colour_statistics",
    "raw_fingerprint",
    "recipe_components",
    "statistics_difference",
]
