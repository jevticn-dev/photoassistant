"""PhotoAssistant — photo editing library.

This package is a **library**, not a service. It must not import FastAPI or
anything from ``service/``; that boundary is checked by a test, because the same
library is imported both by the FastAPI service and by the offline pipeline
(``pipeline/``). The renderer, the fitting loop and the embeddings therefore
exist **once**.

Submodules and the phase that fills each one:

===================  =====  ==============================================
Submodule            Phase  Contents
===================  =====  ==============================================
``schema``           1      edit schema model, validation, versioning
``renderer``         1      implementation of RENDERER_SPEC.md (NumPy)
``fitting``          2      parameter optimisation over a before/after pair
``embeddings``       2      CLIP, DINOv2, colour statistics
``recommender``      3      IEmbedder, IVectorStore, selection strategies
``storage``          2      S3/MinIO and database access
===================  =====  ==============================================
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
