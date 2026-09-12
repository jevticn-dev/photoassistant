"""Give the offline scripts the same environment the containers get.

The library reads container-side variable names — ``S3_ENDPOINT``,
``POSTGRES_HOST`` and so on — because that is what ``infra/docker-compose.yml``
passes to the ML service. A script running on the host reaches the same
containers at different addresses, and ``.env`` keeps those under ``*_LOCAL``
names. This module reads ``.env`` and maps one onto the other, so that the same
library code works from the host without knowing it is on the host.

Nothing is invented here: every value still comes from ``.env``, and a variable
already set in the real environment always wins, so a one-off run can override
anything inline without editing a file.

**Why not ``python-dotenv``.** The file is plain ``KEY=value`` with comments and
no interpolation, which is thirty lines to parse. A dependency that ships in the
library's install just to read those thirty lines is a poor trade, and the
mapping from ``*_LOCAL`` is ours regardless — no package knows about it.

**Why this lives in ``pipeline/`` and not in the library.** The library must not
know whether it runs on a host or in a container; it takes configuration as an
argument. Deciding *which* configuration to hand it is the caller's business, and
here the caller is the offline pipeline.
"""

import os
from collections.abc import MutableMapping
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPOSITORY_ROOT / ".env"

# Host-side value -> the name the library reads. Left is what .env defines for
# reaching a container from outside; right is what compose sets inside one.
LOCAL_OVERRIDES: dict[str, str] = {
    "POSTGRES_HOST_LOCAL": "POSTGRES_HOST",
    "S3_ENDPOINT_LOCAL": "S3_ENDPOINT",
}

# Names .env uses for the MinIO root credentials, which the library reads under
# neutral S3 names — the code must not know that MinIO is what is running.
CREDENTIAL_ALIASES: dict[str, str] = {
    "MINIO_ROOT_USER": "S3_ACCESS_KEY",
    "MINIO_ROOT_PASSWORD": "S3_SECRET_KEY",
}


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a ``KEY=value`` file. Comments, blank lines and ``export`` tolerated.

    Surrounding quotes are stripped, because a value written ``"abc"`` in a file
    that is also sourced by a shell means ``abc``, and a password carrying two
    stray quote characters fails in a way that reads as "wrong password".
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load(
    *, env_file: Path | None = None, environ: MutableMapping[str, str] | None = None
) -> dict[str, str]:
    """Populate the environment from ``.env`` and return what is now in effect.

    Precedence, strongest first:

    1. what is already in the environment — an inline override stays in charge
    2. the ``*_LOCAL`` and credential mappings from ``.env``
    3. plain entries from ``.env``

    The returned values are the ones actually in force, not the ones the file
    proposed. Those differ exactly when something was overridden inline, which is
    the case a report most needs to show correctly.
    """
    target = os.environ if environ is None else environ
    from_file = parse_env_file(ENV_FILE if env_file is None else env_file)

    resolved: dict[str, str] = {}

    def offer(name: str, value: str) -> None:
        if not value:
            return
        target.setdefault(name, value)
        resolved[name] = target[name]

    for key, value in from_file.items():
        if key in LOCAL_OVERRIDES or key in CREDENTIAL_ALIASES:
            continue
        offer(key, value)

    for source, name in LOCAL_OVERRIDES.items():
        offer(name, from_file.get(source, ""))

    for source, name in CREDENTIAL_ALIASES.items():
        offer(name, from_file.get(source, ""))

    return resolved
