"""Recommendation — similarity search and picking three distinct suggestions.

Filled in **phase 3** (which is also the Computer Vision course project).

Three interfaces, and they are the **seams for the ablation study** — each
experimental arm is another implementation of the same interface, not a branch in
an ``if``:

``IEmbedder``
    CLIP by default; arms: DINOv2, a combination.

``IVectorStore``
    pgvector with an HNSW index inside Postgres by default (ADR-5). Qdrant
    remains available as an evaluation arm.

``IRecommendationStrategy``
    MMR over style fingerprints by default (tunable λ); alternatives: k-means
    into 3 clusters then the best of each, and "top-3 without diversity" as a
    **mandatory baseline** (ADR-11).

Flow: CLIP embedding of the query → k=50 most similar photos → a pool of roughly
250 candidate edits → three that differ from each other.

Honest limit of v1: FiveK edits are **corrective**, so the three suggestions are
three approaches to correction rather than three dramatic styles. Drama arrives
with presets through the same mechanism. This is stated explicitly in the thesis.
"""
