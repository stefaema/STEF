import pytest

from shared import logs
from shared.diagnostics import (
    CANCELLED,
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    WARNED,
    run_log,
    verdict,
)


@pytest.fixture
def recorded():
    kept: list = []
    logs.logger.remove()
    logs.logger.configure(extra=dict(logs.DEFAULTS))
    logs.logger.add(kept.append, level="DEBUG", format=logs.file_format)
    yield kept
    logs.logger.remove()


def levels(kept):
    return [one.record["level"].name for one in kept]


def messages(kept):
    return [str(one.record["message"]) for one in kept]


def run(oven, key, **values):
    oven.run_test(key, values, lambda said: None)


def test_a_run_records_its_start_every_step_and_its_end(oven, recorded):
    run(oven, "heat.Preheat", celsius=180)

    assert messages(recorded)[0] == "fixture.heat.Preheat(celsius=180) started"
    assert messages(recorded)[-1].startswith("fixture.heat.Preheat passed")
    assert len(recorded) == 5


def test_a_passing_step_is_kept_without_being_shown(oven, recorded):
    run(oven, "heat.Preheat", celsius=180)

    assert levels(recorded) == ["INFO", "DEBUG", "DEBUG", "DEBUG", "INFO"]


def test_a_step_that_fails_carries_the_reason_it_failed(oven, recorded):
    run(oven, "heat.Breaks")

    assert "First failed: RuntimeError: the element is open circuit" in messages(
        recorded
    )
    assert levels(recorded)[-1] == "ERROR"


def test_an_end_that_errors_is_written_as_an_error(oven, recorded):
    run(oven, "heat.EndsBadly")

    assert levels(recorded)[-2:] == ["ERROR", "ERROR"]


def test_every_line_of_one_run_carries_the_run_s_name_and_start(oven, recorded):
    run(oven, "heat.Preheat", celsius=180)

    bound = {
        (one.record["extra"]["routine"], one.record["extra"]["started"])
        for one in recorded
    }
    assert len(bound) == 1
    assert bound.pop()[0] == "fixture.heat.Preheat"


def test_the_verdict_is_the_worst_status_a_run_produced():
    assert verdict([PASSED, WARNED, FAILED, ERROR]) is ERROR
    assert verdict([PASSED, WARNED, FAILED]) is FAILED
    assert verdict([PASSED, CANCELLED, FAILED]) is FAILED
    assert verdict([PASSED, WARNED, CANCELLED]) is CANCELLED
    assert verdict([PASSED, WARNED]) is WARNED
    assert verdict([PASSED, SKIPPED]) is PASSED
    assert verdict([SKIPPED]) is SKIPPED
    assert verdict([]) is PASSED


def test_the_moment_a_run_began_is_fine_enough_to_tell_two_of_them_apart():
    assert len({run_log.start_time() for _ in range(50)}) == 50
