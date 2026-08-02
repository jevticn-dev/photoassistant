"""Fitting — reconstructing a recipe from a before/after pair.

Filled in **phase 2**. Depends on ``renderer`` and ``schema``.

For each expert edit, the values of **our** parameters are searched for such
that, rendered over the "before" image, they minimise the mean ΔE against the
expert's TIFF. The target is the **image**, not the parameter (ADR-2).

* comparison is 512px against 512px, downscaled by the same algorithm on both sides
* optimiser: ``scipy.optimize.least_squares``
* initialisation: the analytic mapping from ``docs/edit_schema_v1.md`` §4
* output: a recipe plus the **residual error**, written to ``examples.fit_error``

Why this is not a translation of Lightroom parameters: PV2010 semantics are
undocumented, so the error would be uncontrolled and unmeasurable. This way the
system behaves identically for an edit made in any other tool.

The residual is **measured and reported**, not hidden — our tone region masks are
simpler than Lightroom's, so reproduction is not always exact. The distribution
of that residual across 25,000 edits is one of the evaluation metrics.
"""
