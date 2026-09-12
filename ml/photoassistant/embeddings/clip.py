"""CLIP embedding of the "before" image — what is in the scene.

This answers the search question: "what did experts do to scenes like this one".
The user's photograph is encoded the same way and the nearest vectors in
``photos.clip_embedding`` are the candidates. It says nothing about editing; the
edit is described by the style fingerprint, which is a different vector for a
different question (``docs/notes`` §B37, §B38).

**This is the only module in the library that touches torch.** It is imported
lazily, inside the constructor, and ``embeddings/__init__.py`` does not import
this file at all. That keeps ``import photoassistant.embeddings`` working in an
environment without the ``embeddings`` extra installed — which is what CI and the
ordinary test run get, and what makes "torch is not a library dependency" a fact
the installer enforces rather than an intention (``.claude/rules/ml_service.md``).
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Self

import numpy as np
from numpy.typing import NDArray

# ViT-B/32 produces 512 numbers whichever weights it carries, which is why
# photos.clip_embedding could be declared vector(512) back in phase 0.
EMBEDDING_DIMENSION: Final[int] = 512

DEFAULT_MODEL: Final[str] = "ViT-B-32"

# LAION-2B rather than the original OpenAI weights: same architecture, same 512
# outputs, stronger on retrieval, and openly documented training data. Swapping
# them is one name here plus a recomputation of 5.000 photographs — minutes, not
# hours — so this is a cheaply reversible choice, taken now rather than deferred
# (§B41). Verify the exact tag against open_clip.list_pretrained() if it fails.
DEFAULT_PRETRAINED: Final[str] = "laion2b_s34b_b79k"

# Large enough that the per-batch overhead disappears, small enough that a batch
# of 512px images stays well inside memory on CPU.
DEFAULT_BATCH_SIZE: Final[int] = 32


@dataclass(frozen=True)
class ClipConfig:
    """Which encoder to run and where.

    Unlike the storage configuration, missing values here are defaulted rather
    than refused. The reason for refusing an absent endpoint is that a silent
    fallback to localhost looks like a network fault later; an absent model name
    has no such trap — there is one right answer and it is written above.
    """

    model: str = DEFAULT_MODEL
    pretrained: str = DEFAULT_PRETRAINED
    device: str = "cpu"
    batch_size: int = DEFAULT_BATCH_SIZE
    threads: int = 0

    @classmethod
    def from_environment(cls) -> Self:
        return cls(
            model=os.environ.get("CLIP_MODEL", DEFAULT_MODEL),
            pretrained=os.environ.get("CLIP_PRETRAINED", DEFAULT_PRETRAINED),
            device=os.environ.get("CLIP_DEVICE", "cpu"),
            batch_size=int(os.environ.get("CLIP_BATCH_SIZE", DEFAULT_BATCH_SIZE)),
            threads=int(os.environ.get("CLIP_THREADS", "0")),
        )


class ClipEncoder:
    """A loaded CLIP image encoder. Build once, encode many.

    Loading the weights takes seconds and allocating them per batch would dwarf
    the work, so the pipeline keeps one instance for the whole run.
    """

    def __init__(self, config: ClipConfig | None = None) -> None:
        self.config = config or ClipConfig()

        # Imported here, not at module scope: this module may be *present* in an
        # installation that has no torch, and only calling it should fail.
        try:
            import open_clip
            import torch
        except ImportError as error:  # pragma: no cover - depends on the install
            raise RuntimeError(
                "the embeddings extra is not installed. Run "
                "`uv sync --project ml --extra embeddings`."
            ) from error

        self._torch = torch

        if self.config.threads > 0:
            # Left alone by default. The pipeline sets it when something else is
            # already using the cores, so that two jobs do not each size their
            # thread pool to the whole machine and end up slower than one.
            torch.set_num_threads(self.config.threads)

        model, _, preprocess = open_clip.create_model_and_transforms(
            self.config.model, pretrained=self.config.pretrained
        )
        model.eval()
        self._model = model.to(self.config.device)
        self._preprocess = preprocess

    def encode(self, images: Sequence[NDArray[np.floating]]) -> NDArray[np.float32]:
        """Encode a batch of sRGB images into unit-length vectors.

        Each image is height x width x 3 in [0, 1]. The result is one row per
        image, ``EMBEDDING_DIMENSION`` wide.

        **The rows are L2-normalised**, and that is not decoration. An index is
        built for one distance measure and must be queried with the same one; a
        mismatch returns wrong neighbours and reports no error, because both
        queries are perfectly valid. On unit-length vectors cosine and Euclidean
        distance rank identically, so the mismatch cannot arise (§B44). CLIP is
        trained so that the *direction* carries the meaning in any case.
        """
        if not images:
            return np.zeros((0, EMBEDDING_DIMENSION), dtype=np.float32)

        from PIL import Image

        batch = self._torch.stack(
            [
                self._preprocess(
                    Image.fromarray(
                        (np.clip(np.asarray(image), 0.0, 1.0) * 255.0)
                        .round()
                        .astype(np.uint8)
                    )
                )
                for image in images
            ]
        ).to(self.config.device)

        with self._torch.no_grad():
            features = self._model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True)

        vectors = features.cpu().numpy().astype(np.float32)
        if vectors.shape[1] != EMBEDDING_DIMENSION:
            raise RuntimeError(
                f"{self.config.model} produced {vectors.shape[1]} dimensions, but the "
                f"photos.clip_embedding column is vector({EMBEDDING_DIMENSION})"
            )
        return vectors

    def describe(self) -> dict[str, Any]:
        """What was actually loaded. Goes into the phase report."""
        return {
            "model": self.config.model,
            "pretrained": self.config.pretrained,
            "device": self.config.device,
            "batch_size": self.config.batch_size,
            "dimension": EMBEDDING_DIMENSION,
        }
