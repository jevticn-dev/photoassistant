"""Configuration is read from the environment, and refuses rather than guesses."""

import pytest

from photoassistant.storage.config import (
    DEFAULT_REGION,
    ConfigurationError,
    DatabaseConfig,
    ObjectStorageConfig,
)

COMPLETE_S3 = {
    "S3_ENDPOINT": "http://localhost:9000",
    "S3_ACCESS_KEY": "key",
    "S3_SECRET_KEY": "secret",
    "S3_BUCKET_ORIGINALS": "originals",
    "S3_BUCKET_DERIVATIVES": "derivatives",
    "S3_BUCKET_EXPORTS": "exports",
}

COMPLETE_DB = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5433",
    "POSTGRES_USER": "photoassistant",
    "POSTGRES_PASSWORD": "p@ss:word/with@specials",
    "POSTGRES_DB": "photoassistant",
}


def test_object_storage_reads_every_value_from_the_environment():
    config = ObjectStorageConfig.from_environment(COMPLETE_S3)

    assert config.endpoint == "http://localhost:9000"
    assert config.derivatives_bucket == "derivatives"
    assert config.region == DEFAULT_REGION


@pytest.mark.parametrize("missing", sorted(COMPLETE_S3))
def test_object_storage_refuses_when_a_variable_is_missing(missing):
    """Refusing beats defaulting.

    An endpoint that quietly falls back to localhost fails much later, in the
    middle of a run, and looks like a network problem rather than a missing
    variable.
    """
    environment = {key: value for key, value in COMPLETE_S3.items() if key != missing}

    with pytest.raises(ConfigurationError, match=missing):
        ObjectStorageConfig.from_environment(environment)


def test_blank_is_treated_as_missing():
    """An empty variable is a variable somebody meant to set, not an empty value."""
    with pytest.raises(ConfigurationError, match="S3_ACCESS_KEY"):
        ObjectStorageConfig.from_environment({**COMPLETE_S3, "S3_ACCESS_KEY": "   "})


def test_database_port_defaults_and_parses():
    assert DatabaseConfig.from_environment(COMPLETE_DB).port == 5433

    without_port = {key: value for key, value in COMPLETE_DB.items() if key != "POSTGRES_PORT"}
    assert DatabaseConfig.from_environment(without_port).port == 5432


def test_database_port_must_be_a_number():
    with pytest.raises(ConfigurationError, match="POSTGRES_PORT"):
        DatabaseConfig.from_environment({**COMPLETE_DB, "POSTGRES_PORT": "5433a"})


def test_conninfo_carries_a_password_that_would_break_a_url():
    """Keyword pairs, not a URL.

    The password in this test contains ``@``, ``:`` and ``/``. In a URL each of
    those would have to be percent-encoded, and forgetting one produces an
    authentication failure rather than a parse error — which sends you looking at
    the database instead of at the string.
    """
    conninfo = DatabaseConfig.from_environment(COMPLETE_DB).conninfo

    assert "password=p@ss:word/with@specials" in conninfo
    assert "host=localhost" in conninfo
    assert "dbname=photoassistant" in conninfo


def test_repr_does_not_leak_the_password():
    """These objects reach tracebacks and logs, and one of them holds a secret."""
    text = repr(DatabaseConfig.from_environment(COMPLETE_DB))

    assert "p@ss:word/with@specials" not in text
    assert "password=***" in text
