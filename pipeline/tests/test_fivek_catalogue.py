"""Which edits the schema cannot represent, and what the real catalogue contains.

Two kinds of test. The first works on hand-written settings blocks and always
runs. The second opens the actual catalogue and asserts the counts this phase was
planned around; it skips without ``FIVEK_DATASET_PATH``, which is the case in CI.

That second kind is worth its awkwardness. The plan, the schema document and the
exclusion rules all rest on an analysis done once in phase 0. Asserting the
numbers turns "we believe the catalogue looks like this" into something that
fails out loud if it ever stops being true.
"""

import os
from pathlib import Path

import pytest

from pipeline.fivek import catalogue
from pipeline.fivek.catalogue import exclusion_reason, notes_for

PLAIN = {"Exposure": "1", "Contrast": "20", "Shadows": "10"}


def test_an_ordinary_edit_is_not_excluded():
    assert exclusion_reason(PLAIN, "Exposure = 1") is None


def test_the_grayscale_mixer_excludes_the_edit():
    """Seven edits touch it. The schema has no grayscale block, and the change is
    invisible in the parameters we do model — it would read as a failed fit."""
    assert exclusion_reason({**PLAIN, "GrayMixerRed": "20"}, "") == "grayscale"
    assert exclusion_reason({**PLAIN, "ConvertToGrayscale": "true"}, "") == "grayscale"


def test_local_corrections_are_found_in_the_raw_text_not_the_key_pairs():
    """Brush and gradient corrections are nested structures, not key = value pairs,
    so the regex that reads settings cannot see them at all."""
    assert exclusion_reason(PLAIN, "PaintBasedCorrections = { ... }") == "local"
    assert exclusion_reason(PLAIN, "GradientBasedCorrections = { ... }") == "local"


def test_a_crop_excludes_the_edit():
    """Plan §3 keeps crop out of the look, and a cropped result cannot be compared
    pixel for pixel with the uncropped starting image anyway."""
    assert exclusion_reason({**PLAIN, "CropBottom": "0.8"}, "") == "crop"


def test_clarity_is_noted_but_does_not_exclude():
    """Sixteen edits use it and the schema does not model it.

    Discarding them would hide a known limitation; keeping them lets it show up
    honestly as residual error in the report.
    """
    assert exclusion_reason({**PLAIN, "Clarity": "25"}, "") is None
    assert "clarity" in notes_for({**PLAIN, "Clarity": "25"})
    assert "clarity" not in notes_for({**PLAIN, "Clarity": "0"})


def test_the_named_curve_is_noted():
    assert "medium-contrast-curve" in notes_for({"ToneCurveName": '"Medium Contrast"'})
    assert notes_for({"ToneCurveName": '"Linear"'}) == ()


# --------------------------------------------------------------------------
# Against the real catalogue. Skipped without the dataset, as in CI.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def connection():
    raw = os.environ.get("FIVEK_DATASET_PATH", "")
    if not raw:
        pytest.skip("FIVEK_DATASET_PATH is not set")
    try:
        path = catalogue.locate(Path(raw))
    except catalogue.CatalogueError as error:
        pytest.skip(str(error))

    handle = catalogue.open_readonly(path)
    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture(scope="module")
def parsed(connection):
    return catalogue.read_edits(connection)


def test_the_catalogue_holds_five_thousand_photographs_and_five_experts(parsed):
    edits, baseline = parsed

    assert len(baseline) == 5000
    assert len(edits) == 25000
    assert {edit.expert for edit in edits} == set(catalogue.EXPERTS)


def test_the_exclusion_counts_are_the_ones_the_plan_was_written_from(parsed):
    """Measured 2026-08-29 and agreeing with the phase 0 analysis.

    If these move, either the catalogue is not the one we analysed or the
    detection changed — both worth stopping for.
    """
    edits, _ = parsed
    reasons = {}
    for edit in edits:
        if edit.excluded_reason:
            reasons[edit.excluded_reason] = reasons.get(edit.excluded_reason, 0) + 1

    assert reasons == {"grayscale": 7, "local": 2, "crop": 5, "rotated": 5}


def test_the_curve_split_matches_the_schema_document(parsed):
    """`edit_schema` §4 states 87,6% Linear and 12,4% Medium Contrast."""
    edits, _ = parsed
    medium = sum(1 for edit in edits if "medium-contrast-curve" in edit.notes)

    assert medium == 3099
    assert round(medium / len(edits) * 100, 1) == 12.4


def test_every_photograph_has_a_neutral_baseline(parsed):
    """The white balance mapping needs it, and a missing one would silently become
    a zero shift rather than an error."""
    edits, baseline = parsed

    assert {edit.reference for edit in edits} <= set(baseline)


def test_collection_ids_are_found_by_name(connection):
    """The probe hard-coded 930899 for expert C. This is why that is not repeated."""
    collections = catalogue.collection_ids(connection)

    assert {"A", "B", "C", "D", "E", "InputAsShotZeroed"} <= set(collections)


def test_tags_use_one_value_per_controlled_field(connection):
    """The vocabularies were read off the catalogue by arithmetic: every photograph
    tagged `dof` carries exactly one depth value, and the three counts sum to the
    total. A second value would mean the encoding was misread."""
    tags = catalogue.read_tags(connection)

    assert len(tags) == 1065
    for entry in tags.values():
        assert entry.get("depth_of_field") in (None, "deep", "shallow", "interm")
        assert entry.get("light_direction") in (None, "side", "back", "front")


def test_no_photographer_name_survives_into_the_tags(connection):
    """Names are people, not properties of the scene, and the repository is public."""
    tags = catalogue.read_tags(connection)
    allowed = {"subjects", "depth_of_field", "light_direction", "light_type"}

    assert {key for entry in tags.values() for key in entry} <= allowed


def test_a_rotated_edit_is_excluded():
    """One photograph, turned upright by all five experts.

    Rotation is not in the develop settings — it lives on the image row — so
    looking for it among the Crop keys found nothing, and five edits reached the
    fitting pass. There the shapes did not match and the guard raised rather than
    resizing one to the other, which would have put a geometric error into a
    colour measurement.
    """
    assert exclusion_reason(PLAIN, "", rotated=True) == "rotated"
    assert exclusion_reason(PLAIN, "", rotated=False) is None
