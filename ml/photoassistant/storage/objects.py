"""Reading and writing objects over the S3 API (ADR-12).

MinIO is what runs locally, but nothing here says so: the client is given an
endpoint, a key pair and bucket names, all from configuration. Moving to
Cloudflare R2 or Backblaze B2 is a change of three environment variables.

**Two settings that are not optional against MinIO**, and are the usual reason a
first attempt fails with something unhelpful:

``addressing_style="path"``
    Amazon addresses a bucket as part of the hostname
    (``bucket.s3.amazonaws.com``), which is boto3's default. A MinIO on
    ``localhost:9000`` has no wildcard DNS underneath it, so the same request
    resolves nowhere. Path style puts the bucket in the URL instead
    (``localhost:9000/bucket/key``).

``signature_version="s3v4"``
    MinIO only accepts version 4 signatures. boto3 usually picks it, but "usually"
    is not a property to rely on across releases.
"""

from collections.abc import Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from photoassistant.storage.config import ObjectStorageConfig

# Retries are the client's job, not the caller's: a transient 500 from object
# storage is noise, and the pipeline makes hundreds of thousands of these calls.
# Adaptive mode also backs off when the server signals throttling.
_CLIENT_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    retries={"max_attempts": 5, "mode": "adaptive"},
)


class ObjectStore:
    """A thin wrapper over the S3 client, holding the bucket names with it.

    Thin on purpose. It exists so that callers do not repeat the client
    construction and the bucket lookup, not to hide S3 behind an abstraction that
    would have to grow every time something new is needed.
    """

    def __init__(self, config: ObjectStorageConfig) -> None:
        self._config = config
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
            config=_CLIENT_CONFIG,
        )

    @property
    def derivatives(self) -> str:
        return self._config.derivatives_bucket

    @property
    def originals(self) -> str:
        return self._config.originals_bucket

    @property
    def exports(self) -> str:
        return self._config.exports_bucket

    def ensure_buckets(self, buckets: Iterable[str] | None = None) -> list[str]:
        """Create any of the configured buckets that do not exist yet.

        Idempotent, and called at pipeline start rather than per object: a bucket
        that has to exist before the first write should fail at startup, not in
        the middle of a nine-hour run.

        Returns the names it had to create, so a caller can log the difference
        between "found everything" and "set up a fresh store".
        """
        wanted = list(buckets) if buckets is not None else [
            self._config.originals_bucket,
            self._config.derivatives_bucket,
            self._config.exports_bucket,
        ]

        created: list[str] = []
        for bucket in wanted:
            try:
                self._client.head_bucket(Bucket=bucket)
            except ClientError as error:
                # 404 means absent, which is the case worth handling. Anything
                # else — 403 from wrong credentials, a connection failure — is a
                # real problem and must not be swallowed into a create attempt.
                if _status_of(error) != 404:
                    raise
                self._client.create_bucket(Bucket=bucket)
                created.append(bucket)
        return created

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        """Write one object, replacing whatever was there.

        Overwriting rather than refusing is what makes a re-run of a step safe: a
        step interrupted after the upload but before the manifest was marked will
        run again, and the second write has to be allowed to land.
        """
        self._client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, bucket: str, key: str) -> bytes:
        """Read one object whole. Derivatives are small; nothing here streams."""
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def exists(self, bucket: str, key: str) -> bool:
        """Whether an object is there.

        Not a substitute for the manifest. This answers "is the file present",
        while the manifest answers "was the step finished" — and the gap between
        those two is exactly where a crash leaves a half-done photograph.
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if _status_of(error) in (403, 404):
                return False
            raise
        return True


def _status_of(error: ClientError) -> int:
    """HTTP status behind a botocore error, or 0 when it carries none."""
    return int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
