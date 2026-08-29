"""The fetcher's decisions, without touching the network.

What is asserted here is what the run plan says: which steps exist, in what order
they are attempted, and where each derivative lands. The fetching itself is one
loop over urllib and is exercised by running it.
"""

import pytest

from pipeline.fetch_derive import ALL_EXPERTS, BEFORE_RENDITION, plan, strided

NAMES = [f"a{index:04d}-photo" for index in range(1, 5001)]


def test_stride_is_a_permutation():
    """Every photograph exactly once. A stride that shared a factor with the
    length would revisit a subset and silently skip the rest."""
    assert sorted(strided(NAMES)) == sorted(NAMES)


def test_stride_spreads_any_prefix_over_the_whole_catalogue():
    """The point of the reordering.

    Names are grouped by photographer, so alphabetical order would give the first
    thousand finished photographs the same few cameras and scenes — and the
    calibration pass over ~1000 edits starts on whatever has landed.
    """
    positions = [NAMES.index(name) for name in strided(NAMES)[:1000]]

    # Spread across all five fifths of the catalogue, not clustered in one.
    fifths = {position // 1000 for position in positions}
    assert fifths == {0, 1, 2, 3, 4}


@pytest.mark.parametrize("count", [0, 1, 2, 7])
def test_stride_survives_small_and_empty_inputs(count):
    names = NAMES[:count]

    assert sorted(strided(names)) == sorted(names)


def test_plan_produces_one_before_and_one_after_per_expert():
    items = plan(NAMES[:10], ALL_EXPERTS)

    assert len(items) == 10 * (1 + 5)
    assert sum(1 for item in items if item.expert is None) == 10


def test_the_before_rendition_comes_first_for_each_photograph():
    """It is shared by all five experts and no fit can start without it."""
    items = plan(NAMES[:3], ("a", "b"))

    assert [item.expert for item in items] == [None, "a", "b", None, "a", "b", None, "a", "b"]


def test_only_the_before_rendition_gets_a_proxy():
    """The editor previews a photograph, not each expert's version of it."""
    items = plan(NAMES[:4], ALL_EXPERTS)

    assert all(item.with_proxy is (item.expert is None) for item in items)


def test_urls_and_keys_are_built_from_the_reference():
    before, after = plan(["a0001-photo"], ("c",))

    assert before.url.endswith(f"/{BEFORE_RENDITION}/a0001-photo.tif")
    assert before.keys == {
        "fit": "fivek/a0001-photo/pre512.png",
        "proxy": "fivek/a0001-photo/proxy2048.jpg",
    }
    assert after.url.endswith("/tiff16_c/a0001-photo.tif")
    assert after.keys == {"fit": "fivek/a0001-photo/after512-c.png"}


def test_step_names_separate_the_experts():
    """One manifest row per expert, so a restart resumes per expert rather than
    treating a photograph as all-or-nothing."""
    items = plan(["a0001-photo"], ALL_EXPERTS)

    assert [item.step for item in items] == [
        "derive_before",
        "derive_after:a",
        "derive_after:b",
        "derive_after:c",
        "derive_after:d",
        "derive_after:e",
    ]


def test_a_partial_expert_selection_narrows_the_plan():
    items = plan(NAMES[:5], ("c",))

    assert len(items) == 10
    assert {item.expert for item in items} == {None, "c"}
