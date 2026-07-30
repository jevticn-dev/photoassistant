"""Storage — access to object storage and to the database.

Filled in **phase 2**.

Object storage through the **S3 API** (ADR-12), with MinIO locally. The code never
mentions MinIO: it knows an endpoint, credentials and bucket names, all of which
come from configuration. Moving to Cloudflare R2 or Backblaze B2 is a
configuration change, not a code change.

Buckets are split by purpose, because their lifetimes differ:

===============  =====================================================
``originals``    user uploads, untouched
``derivatives``  "before" 512, proxy 2048, "after" 512 — recomputable
``exports``      rendered full-resolution images for download
===============  =====================================================

Database: this module reads and writes ``photos``, ``examples`` and the vector
columns directly. The tables themselves are **created by the backend** through EF
migrations — the pipeline and the service only insert rows into an existing schema.

Hard rule: ``Dataset/`` is a **read-only** input. The pipeline does not write to
it, move anything in it or delete anything from it. ``fivek.lrcat`` is a SQLite
database and is opened read-only, always.
"""
