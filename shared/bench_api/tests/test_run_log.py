"""What a run writes down about itself, which no routine had to ask for."""

import pytest

from shared import bench_api, logs
from shared.bench_api import FAILED, PASSED, SKIPPED, WARNED, run_log


@pytest.fixture
def recorded():
    """Return every record a run produces, at the weight the file keeps them."""
    kept: list = []
    logs.logger.remove()
    logs.logger.configure(extra=dict(logs.DEFAULTS))
    logs.logger.add(kept.append, level="DEBUG", format=logs.file_format)
    yield kept
    logs.logger.remove()


def levels(kept, name: str) -> list[str]:
    """Return the level of every record one routine caused."""
    return [
        one.record["level"].name
        for one in kept
        if one.record["extra"].get("routine", "").endswith(name)
    ]


def messages(kept) -> list[str]:
    """Return what was said, without the columns it was said in."""
    return [str(one.record["message"]) for one in kept]


def run(oven, key, **values):
    """Run one routine to the end."""
    for _ in bench_api.run_routine(oven.routines[key], values):
        pass


# ── That it is written at all ────────────────────────────────────────────────


def test_a_run_records_its_start_every_step_and_its_end(oven, recorded):
    run(oven, "routines.ramp", celsius=180)

    assert len(recorded) == 5
    assert messages(recorded)[0].endswith("started")
    assert messages(recorded)[-1].startswith("fixture.routines.ramp passed")


def test_the_start_says_what_the_run_was_asked_for(oven, recorded):
    run(oven, "routines.ramp", celsius=180)

    assert "celsius=180" in messages(recorded)[0]


def test_a_routine_that_takes_nothing_says_so_without_empty_brackets(oven, recorded):
    run(oven, "routines.read_each_step")

    assert messages(recorded)[0] == "fixture.routines.read_each_step started"


# ── The weight that decides which sink sees it ───────────────────────────────


def test_a_passing_step_is_kept_without_being_shown(oven, recorded):
    run(oven, "routines.ramp", celsius=180)

    assert levels(recorded, "ramp") == ["INFO", "DEBUG", "DEBUG", "DEBUG", "INFO"]


def test_a_step_that_warns_is_loud_enough_for_a_screen(oven, recorded):
    run(oven, "routines.check_probe")

    assert "WARNING" in levels(recorded, "check_probe")


def test_a_step_that_fails_carries_the_reason_it_failed(oven, recorded):
    run(oven, "routines.ramp_that_breaks")

    said = [one for one in messages(recorded) if "open circuit" in one]
    assert said and "failed" in said[0]


# ── How the whole run settled ────────────────────────────────────────────────


def test_a_run_ends_at_the_weight_of_its_worst_step(oven, recorded):
    run(oven, "routines.ramp_that_breaks")

    assert levels(recorded, "ramp_that_breaks")[-1] == "ERROR"


def test_the_verdict_is_the_worst_status_a_run_produced():
    assert run_log.verdict([PASSED, WARNED, FAILED]) is FAILED
    assert run_log.verdict([PASSED, WARNED]) is WARNED
    assert run_log.verdict([PASSED]) is PASSED
    assert run_log.verdict([]) is PASSED


def test_a_ladder_that_settles_early_passed_rather_than_skipped(oven, recorded):
    run(oven, "routines.ramp_that_gives_up")

    assert messages(recorded)[-1].startswith(
        "fixture.routines.ramp_that_gives_up passed"
    )


def test_a_run_that_reached_nothing_at_all_is_the_only_skipped_one():
    assert run_log.verdict([SKIPPED, SKIPPED]) is SKIPPED


def test_a_step_the_preview_never_named_is_recorded_without_its_number(oven, recorded):
    run(oven, "routines.read_each_step")

    assert messages(recorded)[1] == "passed: 21 C"


# ── What names one run ───────────────────────────────────────────────────────


def test_every_line_of_one_run_carries_the_routine_and_the_moment_it_began(
    oven, recorded
):
    run(oven, "routines.ramp", celsius=180)

    bound = {
        (one.record["extra"]["routine"], one.record["extra"]["started"])
        for one in recorded
    }
    assert len(bound) == 1
    assert bound.pop()[0] == "fixture.routines.ramp"


def test_the_moment_a_run_began_is_fine_enough_to_tell_two_of_them_apart():
    began = {run_log.start_time() for _ in range(50)}

    assert len(began) == 50


def test_a_line_nothing_ran_under_names_no_routine(recorded):
    logs.as_component("ccapi.link").debug("connecting")

    assert recorded[0].record["extra"]["routine"] == ""
    assert "[]" not in str(recorded[0])
