"""``IEmbedder`` implementations — the search half of the system.

Only the wrapper lives here. The CLIP encoder itself is phase 2 code and stays
where it is; this module gives it the shape the recommender asks for, and gives
the ablation somewhere to put DINOv2 next to it.

**torch is imported nowhere in this file.** The encoder is built on first use, and
the import happens inside the phase 2 module, so ``import
photoassistant.recommender`` keeps working in an environment without the
``embeddings`` extra — which is what CI and the ordinary test run get.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray


class ClipEmbedder:
    """CLIP ViT-B/32 over LAION-2B weights: the default search embedder.

    The vectors it returns are L2-normalised, which is what lets the cosine index
    and a Euclidean comparison rank identically — the mismatch between how an
    index was built and how it is queried returns wrong neighbours without
    reporting anything, and normalisation removes the possibility rather than
    documenting it (§B44).
    """

    name = "clip"

    def __init__(self, encoder: Any | None = None) -> None:
        self._encoder = encoder

    @property
    def dimension(self) -> int:
        from photoassistant.embeddings.clip import EMBEDDING_DIMENSION

        return EMBEDDING_DIMENSION

    def encode(self, images: Sequence[NDArray[np.floating]]) -> NDArray[np.float32]:
        return self._loaded().encode(images)

    def describe(self) -> dict[str, Any]:
        """Which weights actually answered, for the report."""
        return {"name": self.name, **self._loaded().describe()}

    def _loaded(self) -> Any:
        """Build the encoder the first time it is needed.

        Loading weights costs seconds and a gigabyte of torch. A harness that
        constructs the embedder to read its name — or a test that never encodes
        anything — should not pay for either.
        """
        if self._encoder is None:
            from photoassistant.embeddings.clip import ClipEncoder

            self._encoder = ClipEncoder()
        return self._encoder


class Dinov2Embedder:
    """DINOv2 as the **search** encoder — the other half of the encoder question.

    Task 11 asked which encoder describes an *edit*; this asks which one decides
    what counts as a *similar scene*. They are different jobs and carry different
    prices: a fingerprint is computed offline and the service never sees the model,
    while a search encoder runs on the user's photograph at request time and puts a
    gigabyte of torch into the shipped image (§B78).

    Which is exactly why it is worth measuring: retrieval carries roughly a fifth of
    the distance from doing nothing to doing the best possible, against a twentieth
    for the selection that task 11 tried to improve (§B76). This acts on the step
    that does the work.
    """

    name = "dinov2"

    def __init__(self, encoder: Any | None = None) -> None:
        self._encoder = encoder

    @property
    def dimension(self) -> int:
        return self._loaded().dimension

    def encode(self, images: Sequence[NDArray[np.floating]]) -> NDArray[np.float32]:
        return self._loaded().encode(list(images))

    def describe(self) -> dict[str, Any]:
        return self._loaded().describe()

    def _loaded(self) -> Any:
        if self._encoder is None:
            from photoassistant.embeddings.dinov2 import Dinov2Config, Dinov2Encoder

            self._encoder = Dinov2Encoder(Dinov2Config.from_environment())
        return self._encoder
