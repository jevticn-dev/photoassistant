"""The object store against a real S3 endpoint.

**Skipped when none is reachable.** Almost nothing here is worth asserting against
a mock: what can actually go wrong is the client configuration, and a mock would
be configured by the same assumptions it is supposed to check. The two settings
that matter — path-style addressing and the v4 signature — either work against a
running MinIO or they do not.

    docker compose --env-file .env -f infra/docker-compose.yml up -d minio

Objects are written into a bucket named for the run and the bucket is removed
afterwards, so this never touches the pipeline's data.
"""

import os
import uuid

import pytest

pytest.importorskip("boto3")

from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

from photoassistant.storage.config import ConfigurationError, ObjectStorageConfig  # noqa: E402
from photoassistant.storage.objects import ObjectStore  # noqa: E402


def _configuration(bucket: str) -> ObjectStorageConfig:
    """Settings from the environment, filled in from .env's host-side names.

    The library reads neutral S3 names; a developer running pytest has MinIO's
    root credentials and the *_LOCAL endpoint in .env. The three that differ are
    resolved here rather than by depending on the pipeline's loader from a
    library test.
    """
    environ = dict(os.environ)
    environ.setdefault("S3_ENDPOINT", environ.get("S3_ENDPOINT_LOCAL", "http://localhost:9000"))
    environ.setdefault("S3_ACCESS_KEY", environ.get("MINIO_ROOT_USER", ""))
    environ.setdefault("S3_SECRET_KEY", environ.get("MINIO_ROOT_PASSWORD", ""))
    # The test never touches the configured buckets; it makes its own.
    for name in ("S3_BUCKET_ORIGINALS", "S3_BUCKET_DERIVATIVES", "S3_BUCKET_EXPORTS"):
        environ.setdefault(name, bucket)
    return ObjectStorageConfig.from_environment(environ)


@pytest.fixture
def store():
    bucket = f"test-{uuid.uuid4().hex[:12]}"
    try:
        config = _configuration(bucket)
    except ConfigurationError as error:
        pytest.skip(f"object storage not configured: {error}")

    candidate = ObjectStore(config)
    try:
        candidate.ensure_buckets([bucket])
    except (ClientError, BotoCoreError) as error:
        pytest.skip(f"no object storage at {config.endpoint} — {error}")

    try:
        yield candidate, bucket
    finally:
        _remove_bucket(candidate, bucket)


def _remove_bucket(store: ObjectStore, bucket: str) -> None:
    """Empty the bucket and delete it. S3 refuses to drop one that holds objects."""
    client = store._client  # noqa: SLF001 - teardown, not part of the interface
    listing = client.list_objects_v2(Bucket=bucket)
    for entry in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=entry["Key"])
    client.delete_bucket(Bucket=bucket)


def test_round_trip_keeps_the_bytes_exactly(store):
    """Derivatives are PNG: one flipped byte is a corrupt image, not a worse one."""
    candidate, bucket = store
    payload = bytes(range(256)) * 8

    candidate.put(bucket, "derived/a0001/pre512.png", payload, "image/png")

    assert candidate.get(bucket, "derived/a0001/pre512.png") == payload


def test_writing_twice_replaces_rather_than_refuses(store):
    """A step interrupted after the upload runs again, and the second write must land.

    Refusing here would make every re-run of an interrupted step fail, which is
    the opposite of what the manifest is built for.
    """
    candidate, bucket = store
    candidate.put(bucket, "key", b"first", "application/octet-stream")

    candidate.put(bucket, "key", b"second", "application/octet-stream")

    assert candidate.get(bucket, "key") == b"second"


def test_exists_distinguishes_present_from_absent(store):
    candidate, bucket = store
    candidate.put(bucket, "present", b"x", "application/octet-stream")

    assert candidate.exists(bucket, "present") is True
    assert candidate.exists(bucket, "absent") is False


def test_ensure_buckets_is_idempotent(store):
    """Called at the start of every run, including runs that resume."""
    candidate, bucket = store

    assert candidate.ensure_buckets([bucket]) == []


def test_a_bucket_name_with_dots_still_resolves(store):
    """This is what path-style addressing buys, and why it is not a default.

    Virtual-host addressing would put the bucket in the hostname, where a dotted
    name breaks TLS certificate matching and, against a plain localhost endpoint,
    resolves nowhere at all.
    """
    candidate, _ = store
    dotted = f"test.dotted.{uuid.uuid4().hex[:8]}"
    candidate.ensure_buckets([dotted])

    try:
        candidate.put(dotted, "key", b"payload", "application/octet-stream")
        assert candidate.get(dotted, "key") == b"payload"
    finally:
        _remove_bucket(candidate, dotted)
