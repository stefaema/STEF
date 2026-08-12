from shared import bench_api
from shared.bench_api import FAILED, PASSED, SKIPPED, WARNED

WARMING = "Warming"
HOLDING = "Holding"
COOLING = "Cooling"


def outcomes(oven, key, **values):
    """Return every outcome one routine yields, in order."""
    return list(bench_api.run_routine(oven.routines[key], values))


# ── Every step settles ───────────────────────────────────────────────────────


def test_each_step_carries_the_title_the_preview_promised(oven):
    settled = outcomes(oven, "routines.ramp", celsius=200)

    assert [step.step for step in settled] == [WARMING, HOLDING, COOLING]
    assert [step.status for step in settled] == [PASSED] * 3


def test_a_step_that_names_itself_keeps_its_own_title(oven):
    settled = outcomes(oven, "routines.ramp", celsius=200)

    assert settled[1].detail == "held"
    assert settled[1].step == HOLDING


def test_a_step_that_names_nothing_takes_the_next_row_of_the_preview(oven):
    settled = outcomes(oven, "routines.ramp", celsius=200)

    assert settled[0].step == WARMING


def test_a_routine_with_no_preview_numbers_its_own_rows(oven):
    settled = outcomes(oven, "routines.read_each_step")

    assert [step.step for step in settled] == ["#1", "#2"]
    assert [step.detail for step in settled] == ["21 C", "22 C"]


# ── Ending early ─────────────────────────────────────────────────────────────


def test_giving_up_settles_the_step_that_gave_up_and_skips_the_rest(oven):
    settled = outcomes(oven, "routines.ramp_that_gives_up")

    assert [step.status for step in settled] == [PASSED, PASSED, SKIPPED]
    assert settled[1].detail == "already at temperature"
    assert settled[2].step == COOLING


def test_giving_up_is_not_failing(oven):
    settled = outcomes(oven, "routines.ramp_that_gives_up")

    assert not any(step.status is FAILED for step in settled)


def test_an_uncaught_error_becomes_one_failed_step_and_skips_the_rest(oven):
    settled = outcomes(oven, "routines.ramp_that_breaks")

    assert [step.status for step in settled] == [PASSED, FAILED]
    assert "open circuit" in settled[1].detail


def test_a_routine_that_never_starts_fails_on_its_first_row(oven):
    settled = outcomes(oven, "routines.ramp_that_never_starts")

    assert settled[0].status is FAILED
    assert settled[0].step == WARMING
    assert "no oven here" in settled[0].detail


def test_a_warned_step_does_not_stop_the_run(oven):
    settled = outcomes(oven, "routines.check_probe")

    assert [step.status for step in settled] == [PASSED, WARNED]


# ── What a routine is handed ─────────────────────────────────────────────────


def test_a_routine_reads_its_values_out_of_one_dictionary(oven):
    settled = outcomes(oven, "generated.ramp_once", celsius=250)

    assert settled[0].detail == "250 C"
