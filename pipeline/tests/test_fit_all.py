"""How the calibration sample is drawn."""

from collections import Counter

from pipeline.fit_all import stratified

EXPERTS = ("a", "b", "c", "d", "e")

TASKS = [
    {"reference": f"a{photo:04d}-x", "expert": expert}
    for photo in range(1, 5001)
    for expert in EXPERTS
]


def test_the_sample_is_balanced_across_experts():
    """The flaw this replaced.

    The list runs photograph by photograph with the five experts inside each, so
    it has a period of five, and a plain stride over the whole thing aliases with
    that period. A real run produced 269 edits by expert C against 143 by E.

    It matters because the experts are not equally easy to reconstruct: mean ΔE
    ran from 1.31 for B to 1.86 for C over the same sample. An unbalanced sample
    reports an average of whichever experts it favoured.
    """
    counts = Counter(task["expert"] for task in stratified(TASKS, 1000))

    assert set(counts) == set(EXPERTS)
    assert set(counts.values()) == {200}


def test_the_sample_still_spans_the_whole_catalogue():
    """Balance must not come at the cost of the other spread."""
    references = [task["reference"] for task in stratified(TASKS, 500)]
    positions = sorted(int(reference[1:5]) for reference in references)

    assert min(positions) < 50
    assert max(positions) > 4950
    # Every fifth of the catalogue is represented, not just its ends.
    assert {position // 1000 for position in positions} == {0, 1, 2, 3, 4}


def test_asking_for_everything_returns_everything():
    assert stratified(TASKS, 0) is TASKS
    assert stratified(TASKS, len(TASKS)) is TASKS


def test_a_sample_larger_than_one_expert_group_does_not_repeat():
    """Guards the boundary where a group is smaller than its share."""
    few = [{"reference": f"a{i:04d}-x", "expert": "c"} for i in range(3)]

    sample = stratified(few, 2)

    assert len({id(task) for task in sample}) == len(sample)


def test_a_sample_smaller_than_the_number_of_experts_still_returns_that_many():
    """The edge the first version dropped on the floor.

    With five experts and a sample of four, an even split gives zero each, and
    `--sample 4` quietly fitted nothing at all.
    """
    assert len(stratified(TASKS, 4)) == 4
    assert len(stratified(TASKS, 1)) == 1


def test_the_sample_is_the_size_that_was_asked_for():
    """1000 divides by five; 999 does not, and the remainder must not vanish."""
    for size in (999, 1000, 1001, 137):
        assert len(stratified(TASKS, size)) == size
