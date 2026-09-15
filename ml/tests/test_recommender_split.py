"""The evaluation split as a value: loading, saving, and refusing nonsense.

No database and no images — this is the part of the split that is pure data. What
the split means against the real corpus is checked in
``pipeline/tests/test_make_split.py``, which needs Postgres.
"""

import json

import pytest

from photoassistant.recommender import EvaluationSplit, SplitError


def make(held_out=("a0001", "a0002", "a0003"), drawn_from=10) -> EvaluationSplit:
    return EvaluationSplit(
        seed=1,
        created_at="2026-09-13T12:00:00+00:00",
        drawn_from=drawn_from,
        held_out=tuple(held_out),
    )


def test_membership_is_by_reference():
    split = make()
    assert split.is_held_out("a0002")
    assert not split.is_held_out("a0009")


def test_build_set_is_the_complement_in_the_original_order():
    split = make(held_out=("b", "d"))
    assert split.build_set(["a", "b", "c", "d", "e"]) == ["a", "c", "e"]


def test_empty_split_is_refused():
    with pytest.raises(SplitError, match="empty"):
        make(held_out=())


def test_duplicate_reference_is_refused():
    """A duplicate would make the split smaller than it claims, silently."""
    with pytest.raises(SplitError, match="twice"):
        make(held_out=("a0001", "a0001"))


def test_sample_larger_than_the_corpus_is_refused():
    with pytest.raises(SplitError, match="smaller than the sample"):
        make(held_out=("a", "b", "c"), drawn_from=2)


def test_round_trip_through_a_file_preserves_everything(tmp_path):
    path = tmp_path / "split.json"
    original = make()
    original.save(path)

    assert EvaluationSplit.load(path) == original


def test_saved_file_is_readable_by_a_human(tmp_path):
    """The artefact is read by people and diffed by git, so it is indented JSON."""
    path = tmp_path / "split.json"
    make().save(path)

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\n  " in text

    payload = json.loads(text)
    assert payload["held_out_count"] == 3
    assert payload["held_out"] == ["a0001", "a0002", "a0003"]


def test_missing_file_says_what_to_run(tmp_path):
    with pytest.raises(SplitError, match="make_split"):
        EvaluationSplit.load(tmp_path / "absent.json")


def test_malformed_file_is_refused_rather_than_half_read(tmp_path):
    path = tmp_path / "split.json"
    path.write_text('{"seed": 1}', encoding="utf-8")

    with pytest.raises(SplitError, match="malformed"):
        EvaluationSplit.load(path)


def test_invalid_json_is_refused(tmp_path):
    path = tmp_path / "split.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SplitError, match="valid JSON"):
        EvaluationSplit.load(path)
