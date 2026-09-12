"""The host-side environment mapping: .env in, container-style names out."""

from pipeline.environment import load, parse_env_file

SAMPLE = """\
# A comment, and a blank line follow.

POSTGRES_USER=photoassistant
POSTGRES_PASSWORD=replace-me
POSTGRES_DB=photoassistant
POSTGRES_PORT=5433
POSTGRES_HOST_LOCAL=localhost
MINIO_ROOT_USER=minio-user
MINIO_ROOT_PASSWORD=minio-password
S3_ENDPOINT_LOCAL=http://localhost:9000
S3_BUCKET_DERIVATIVES=derivatives
export JWT_ISSUER=photoassistant
QUOTED="quoted value"
NOT_A_PAIR
"""


def write_env(tmp_path, text=SAMPLE):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_parser_handles_comments_blanks_export_and_quotes(tmp_path):
    values = parse_env_file(write_env(tmp_path))

    assert values["POSTGRES_USER"] == "photoassistant"
    assert values["JWT_ISSUER"] == "photoassistant"
    # Stripped: a value written "abc" in a file a shell may also source means
    # abc, and a password carrying two stray quotes reads as a wrong password.
    assert values["QUOTED"] == "quoted value"
    assert "NOT_A_PAIR" not in values


def test_missing_file_is_empty_not_an_error(tmp_path):
    """A run with everything exported inline is legitimate, not a misconfiguration."""
    assert parse_env_file(tmp_path / "nothing-here") == {}


def test_local_names_become_the_names_the_library_reads(tmp_path):
    environ: dict[str, str] = {}

    load(env_file=write_env(tmp_path), environ=environ)

    assert environ["POSTGRES_HOST"] == "localhost"
    assert environ["S3_ENDPOINT"] == "http://localhost:9000"
    # The library must not know that MinIO is what is running.
    assert environ["S3_ACCESS_KEY"] == "minio-user"
    assert environ["S3_SECRET_KEY"] == "minio-password"


def test_the_source_names_do_not_leak_through_as_themselves(tmp_path):
    """Only the mapped name is set.

    If both were set, code could read either one and the two would silently drift
    apart the first time somebody changed only one of them.
    """
    environ: dict[str, str] = {}

    load(env_file=write_env(tmp_path), environ=environ)

    assert "POSTGRES_HOST_LOCAL" not in environ
    assert "S3_ENDPOINT_LOCAL" not in environ
    assert "MINIO_ROOT_USER" not in environ


def test_an_inline_override_wins_over_the_file(tmp_path):
    """Running one job against another database must not need the file edited."""
    environ = {"POSTGRES_HOST": "192.168.0.10"}

    resolved = load(env_file=write_env(tmp_path), environ=environ)

    assert environ["POSTGRES_HOST"] == "192.168.0.10"
    # And the report shows what was in force, not what the file proposed.
    assert resolved["POSTGRES_HOST"] == "192.168.0.10"


def test_plain_entries_pass_through(tmp_path):
    environ: dict[str, str] = {}

    load(env_file=write_env(tmp_path), environ=environ)

    assert environ["POSTGRES_PORT"] == "5433"
    assert environ["S3_BUCKET_DERIVATIVES"] == "derivatives"
