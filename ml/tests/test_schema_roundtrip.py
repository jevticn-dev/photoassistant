"""Agreement over the shared fixtures, and the validation rules behind it.

The edit schema exists as three models — Python, C# and TypeScript. Agreement is
proven rather than assumed: each parses the same files from ``fixtures/edits/``
and re-serialising must produce the same document (``docs/edit_schema_v1.md``
§8). This is the Python half of that claim.

What "the same document" means, precisely. The comparison is over **parsed
values**, not bytes. Key order and content are canonical, but the text is not
comparable across the three languages: ``JSON.stringify`` in JavaScript writes
``0`` where Python writes ``0.0``, and neither is wrong. Comparing bytes would
turn a language detail into a spurious failure and tempt someone to encode
numbers as strings to work around it.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from photoassistant.schema import SCHEMA_VERSION, EditRecipe, from_json, load, to_json

FIXTURES = Path(__file__).parents[2] / "fixtures" / "edits"

EXPECTED_FIXTURES = ["curve_only", "extreme", "neutral", "warm_bright"]


def _fixture(name: str) -> Path:
    return FIXTURES / f"{name}.json"


def test_the_expected_fixtures_are_present() -> None:
    """Guards the test itself: parametrised tests over an empty directory pass vacuously."""
    found = sorted(path.stem for path in FIXTURES.glob("*.json"))
    assert found == EXPECTED_FIXTURES


@pytest.mark.parametrize("name", EXPECTED_FIXTURES)
def test_round_trip_preserves_the_document(name: str) -> None:
    text = _fixture(name).read_text(encoding="utf-8")

    reserialised = to_json(from_json(text))

    assert json.loads(reserialised) == json.loads(text)


@pytest.mark.parametrize("name", EXPECTED_FIXTURES)
def test_round_trip_is_stable_at_the_model_level(name: str) -> None:
    recipe = load(_fixture(name))

    assert from_json(to_json(recipe)) == recipe


@pytest.mark.parametrize("name", EXPECTED_FIXTURES)
def test_every_fixture_declares_the_supported_version(name: str) -> None:
    assert load(_fixture(name)).version == SCHEMA_VERSION


def test_the_neutral_fixture_is_the_identity_recipe() -> None:
    """`neutral.json` is what the renderer's bit-exactness test renders (SPEC §4.1)."""
    assert load(_fixture("neutral")).is_neutral()


@pytest.mark.parametrize("name", ["warm_bright", "extreme", "curve_only"])
def test_the_other_fixtures_are_not_neutral(name: str) -> None:
    assert not load(_fixture(name)).is_neutral()


def test_curve_only_touches_nothing_but_the_curve() -> None:
    """Isolates the LUT path: any difference it renders comes from the curve alone."""
    recipe = load(_fixture("curve_only"))

    assert recipe.white_balance == EditRecipe().white_balance
    assert recipe.tone == EditRecipe().tone
    assert recipe.color == EditRecipe().color
    assert not recipe.tone_curve.is_neutral()


def test_an_omitted_group_reads_as_neutral_and_is_written_back() -> None:
    """Parsing is lenient about omissions, serialising is not — the canonical form is full."""
    recipe = from_json('{"schema": 1, "color": {"vibrance": 30.0}}')

    assert recipe.tone.exposure == 0.0
    assert recipe.color.saturation == 0.0
    assert recipe.color.vibrance == 30.0

    written = json.loads(to_json(recipe))
    assert set(written) == {"schema", "white_balance", "tone", "color", "tone_curve"}
    assert written["tone_curve"]["points"] == [[0.0, 0.0], [1.0, 1.0]]


def test_a_recipe_with_no_schema_version_is_refused() -> None:
    """A stored document has to say which version it is.

    That is what makes the promise "``schema: 1`` stays readable forever" mean
    anything. The version is defaulted on the model — ``EditRecipe()`` in code is
    a neutral recipe of the version this code speaks — but required when parsing a
    document.

    Found by the C# agreement test: TypeScript refused this and Python accepted
    it, and the two had disagreed since they were written. Which is what a
    three-language agreement test is for.
    """
    with pytest.raises(ValueError, match="must declare a schema version"):
        from_json('{"tone": {"exposure": 1.0}}')


def test_a_newer_schema_is_refused() -> None:
    """edit_schema §7: a reader refuses what it does not understand rather than guessing."""
    with pytest.raises(ValidationError, match="unsupported schema version"):
        from_json('{"schema": 2}')


def test_an_unknown_key_is_refused() -> None:
    """A misspelled parameter silently dropped would render as neutral and hide as fit error."""
    with pytest.raises(ValidationError):
        from_json('{"schema": 1, "tone": {"exposure": 0.0, "clarity": 40.0}}')


@pytest.mark.parametrize(
    "document",
    [
        pytest.param('{"schema": 1, "tone": {"exposure": 5.5}}', id="exposure over +5 stops"),
        pytest.param('{"schema": 1, "tone": {"contrast": 101.0}}', id="contrast over +100"),
        pytest.param(
            '{"schema": 1, "white_balance": {"temperature": -101.0}}',
            id="temperature under -100",
        ),
        pytest.param('{"schema": 1, "color": {"vibrance": 200.0}}', id="vibrance over +100"),
    ],
)
def test_values_outside_the_declared_range_are_refused(document: str) -> None:
    with pytest.raises(ValidationError):
        from_json(document)


@pytest.mark.parametrize(
    "points",
    [
        pytest.param("[[0.0, 0.0]]", id="a single point is not a curve"),
        pytest.param("[[0.2, 0.0], [1.0, 1.0]]", id="does not start at x = 0"),
        pytest.param("[[0.0, 0.0], [0.8, 1.0]]", id="does not end at x = 1"),
        pytest.param("[[0.0, 0.0], [0.5, 0.4], [0.5, 0.6], [1.0, 1.0]]", id="x repeats"),
        pytest.param("[[0.0, 0.0], [0.7, 0.4], [0.3, 0.6], [1.0, 1.0]]", id="x decreases"),
        pytest.param("[[0.0, 0.0], [0.5, 1.4], [1.0, 1.0]]", id="y outside [0, 1]"),
    ],
)
def test_a_curve_breaking_spec_6_1_is_refused(points: str) -> None:
    with pytest.raises(ValidationError):
        from_json(f'{{"schema": 1, "tone_curve": {{"points": {points}}}}}')


def test_a_lifted_black_point_is_allowed() -> None:
    """Only x is constrained to the endpoints; y is free, which is what a faded look needs."""
    recipe = from_json('{"schema": 1, "tone_curve": {"points": [[0.0, 0.1], [1.0, 0.9]]}}')

    assert recipe.tone_curve.points == [(0.0, 0.1), (1.0, 0.9)]
