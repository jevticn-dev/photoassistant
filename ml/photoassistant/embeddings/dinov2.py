"""DINOv2 as a second encoder, for the phase 3 ablation.

CLIP learned from **images paired with captions**, so its features are tied to what
can be named — what is in the scene. DINOv2 learned from images alone, with no text
anywhere, so its features are expected to sit closer to appearance: texture,
material, the distribution of light (§B37).

Whether that matters for describing an *edit* is the question the ablation answers.
It is an expectation, not a finding, and the numbers decide.

**Mirrors ``clip.py`` deliberately.** Same shape, same lazy torch import, same
normalisation, so the two are interchangeable behind ``IEmbedder`` and neither gets
an accidental advantage from being called differently.

**The input size is ours to choose and it is not free.** These are patch-14
models: at the 518px timm defaults to, an image becomes 1369 patches, against 49
for CLIP's ViT-B/32 at 224. The cost difference is measured rather than assumed
(``pipeline.embed_arms --measure``), and the default here is 224 — a multiple of 14,
the same resolution CLIP sees, and the resolution our derivatives are stored at is
512 anyway.
"""

import os
from dataclasses import dataclass
from typing import Any, Final, Self

import numpy as np
from numpy.typing import NDArray

# ViT-S/14 returns 384 numbers; the base model returns 768. The number is a
# property of the model, not a setting (§B64), and it decides the column width if
# this arm ever wins.
SMALL_DIMENSION: Final[int] = 384

DEFAULT_MODEL: Final[str] = "vit_small_patch14_dinov2.lvd142m"

# Small rather than base: four times cheaper, and nothing suggests the larger one
# describes *edits* better. If the ablation makes this arm a contender, the
# comparison is worth repeating with the base model before anything ships.
DEFAULT_IMAGE_SIZE: Final[int] = 224
DEFAULT_BATCH_SIZE: Final[int] = 32


@dataclass(frozen=True)
class Dinov2Config:
    """Everything the encoder needs, from the environment as usual."""

    model: str = DEFAULT_MODEL
    device: str = "cpu"
    image_size: int = DEFAULT_IMAGE_SIZE
    batch_size: int = DEFAULT_BATCH_SIZE

    @classmethod
    def from_environment(cls) -> Self:
        return cls(
            model=os.environ.get("DINOV2_MODEL", DEFAULT_MODEL),
            device=os.environ.get("DINOV2_DEVICE", "cpu"),
            image_size=int(os.environ.get("DINOV2_IMAGE_SIZE", DEFAULT_IMAGE_SIZE)),
            batch_size=int(os.environ.get("DINOV2_BATCH_SIZE", DEFAULT_BATCH_SIZE)),
        )


class Dinov2Encoder:
    """Images in, unit-length vectors out.

    Rows are L2-normalised for the same reason CLIP's are: on unit vectors cosine
    and Euclidean distance rank identically, so an index built for one and queried
    with the other cannot disagree (§B44). It also puts the two encoders on the
    same footing, which an ablation comparing them requires.
    """

    name = "dinov2"

    def __init__(self, config: Dinov2Config | None = None) -> None:
        self.config = config or Dinov2Config()

        # Imported here, never at module scope: the library installs without the
        # embeddings extra and must still import (§21 in stack/python.md).
        import timm
        import torch

        self._torch = torch
        model = timm.create_model(
            self.config.model,
            pretrained=True,
            num_classes=0,
            img_size=self.config.image_size,
        )
        model.eval()
        self._model = model.to(self.config.device)

        # The data config comes from the *pretrained* weights, which were trained at
        # 518px; overriding img_size on the model does not change it, and the
        # mismatch surfaces as an assertion deep inside the patch embedding rather
        # than as a configuration error. The size is therefore forced to match the
        # model that was actually built.
        data_config = timm.data.resolve_model_data_config(model)
        data_config["input_size"] = (3, self.config.image_size, self.config.image_size)
        self._preprocess = timm.data.create_transform(**data_config, is_training=False)

    @property
    def dimension(self) -> int:
        return int(self._model.num_features)

    def encode(self, images: list[NDArray[np.floating]]) -> NDArray[np.float32]:
        """Encode sRGB images in [0, 1], one row per image."""
        if not images:
            return np.zeros((0, self.dimension), dtype=np.float32)

        from PIL import Image

        batch = self._torch.stack(
            [
                self._preprocess(
                    Image.fromarray(
                        (np.clip(np.asarray(image), 0.0, 1.0) * 255.0).round().astype(np.uint8)
                    )
                )
                for image in images
            ]
        ).to(self.config.device)

        with self._torch.no_grad():
            features = self._model(batch)
            features = features / features.norm(dim=-1, keepdim=True)

        return features.cpu().numpy().astype(np.float32)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.config.model,
            "device": self.config.device,
            "image_size": self.config.image_size,
            "batch_size": self.config.batch_size,
            "dimension": self.dimension,
        }
