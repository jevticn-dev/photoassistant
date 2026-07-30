"""Embeddings — vector descriptions of content and of style.

Filled in **phase 2**.

Two different things, answering two different questions:

``clip_embedding`` (content of the "before" image)
    CLIP ViT-B/32, 512 dimensions. Answers "what did experts do to scenes like
    this one". Written to ``photos.clip_embedding``.

``style_fingerprint`` (style of the "after" image)
    Colour statistics (histograms, saturation, luminance distribution) combined
    with a DINOv2 embedding. Used to pick suggestions that differ **from each
    other**. Written to ``examples.style_fingerprint`` and
    ``looks.style_fingerprint``.

    The dimension is **not fixed yet**, which is why those columns are declared
    as ``vector`` without one. Once the composition is settled in this phase, a
    migration fixes the dimension and creates the HNSW index — an index is not
    possible without a fixed dimension.

GPU strategy (plan §5.1, sub-decision 3d): RX 9070 through WSL2+ROCm, falling
back to ONNX+DirectML, falling back to CPU. CPU is acceptable — this is a one-off
job of a few hours.
"""
