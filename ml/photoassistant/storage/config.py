"""Where the storage layer gets its endpoints, credentials and bucket names.

Never from the source. Every value here comes from the environment, which is what
lets the same code run three ways without knowing which one it is in: the offline
pipeline on a developer's machine, the ML service inside a container, and a test.

**Variable names are the container-side ones** — ``S3_ENDPOINT``, ``POSTGRES_HOST``
and so on — because that is what ``infra/docker-compose.yml`` already passes to the
service. A process running on the host reaches the same containers at different
addresses, and ``.env`` keeps those under ``*_LOCAL`` names; mapping one to the
other is the caller's job, not this module's. ``pipeline/environment.py`` does it
for the offline scripts.

The configuration objects are plain frozen dataclasses rather than
``pydantic-settings``: that package belongs to the service extra, and the library
may not depend on it (`.claude/rules/ml_service.md`). They are also **passed as
arguments**, never read from a global — the library has no ambient settings object,
because the pipeline is not a web request.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

# S3 requires a region in the signature even where the concept is meaningless.
# MinIO accepts anything; this is the value everyone uses for "not applicable".
DEFAULT_REGION = "us-east-1"

DEFAULT_POSTGRES_PORT = 5432


class ConfigurationError(RuntimeError):
    """A required environment variable is missing or unusable.

    Raised rather than defaulted. A wrong endpoint that silently falls back to
    localhost fails much later and much less clearly than one that refuses to
    start.
    """


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class ObjectStorageConfig:
    """S3-compatible object storage: one endpoint, one key pair, three buckets.

    The buckets are separate because their lifetimes differ, not for tidiness:
    ``originals`` holds what a user uploaded and may never be regenerated,
    ``derivatives`` holds everything the pipeline can recompute, and ``exports``
    holds rendered files that exist only until they are downloaded.
    """

    endpoint: str
    access_key: str
    secret_key: str
    originals_bucket: str
    derivatives_bucket: str
    exports_bucket: str
    region: str = DEFAULT_REGION

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> ObjectStorageConfig:
        source = os.environ if environ is None else environ
        return cls(
            endpoint=_required(source, "S3_ENDPOINT"),
            access_key=_required(source, "S3_ACCESS_KEY"),
            secret_key=_required(source, "S3_SECRET_KEY"),
            originals_bucket=_required(source, "S3_BUCKET_ORIGINALS"),
            derivatives_bucket=_required(source, "S3_BUCKET_DERIVATIVES"),
            exports_bucket=_required(source, "S3_BUCKET_EXPORTS"),
            region=source.get("S3_REGION", DEFAULT_REGION),
        )


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection details for the Postgres the backend migrated into shape."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> DatabaseConfig:
        source = os.environ if environ is None else environ
        raw_port = source.get("POSTGRES_PORT", str(DEFAULT_POSTGRES_PORT))
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ConfigurationError(f"POSTGRES_PORT is not a number: {raw_port!r}") from error

        return cls(
            host=_required(source, "POSTGRES_HOST"),
            port=port,
            user=_required(source, "POSTGRES_USER"),
            password=_required(source, "POSTGRES_PASSWORD"),
            database=_required(source, "POSTGRES_DB"),
        )

    @property
    def conninfo(self) -> str:
        """A libpq connection string.

        Built as keyword pairs rather than as a URL because a password containing
        ``@``, ``/`` or ``:`` would have to be percent-encoded in a URL, and a
        password that works everywhere except in the connection string is a bad
        afternoon.
        """
        return (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.database}"
        )

    def __repr__(self) -> str:
        """Repr without the password: these objects end up in tracebacks and logs."""
        return (
            f"DatabaseConfig(host={self.host!r}, port={self.port}, user={self.user!r}, "
            f"password=***, database={self.database!r})"
        )
