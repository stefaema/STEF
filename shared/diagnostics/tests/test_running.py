import dataclasses
import threading
import time

import pytest

from shared.diagnostics import (
    CANCELLED,
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    WARNED,
    Prompt,
    PromptClosed,
    SkipReason,
    StepOutcome,
    StopUnconfirmed,
    end,
)
from shared.diagnostics.tests.fixture import heat
from shared.subsystem import Level, LinkState, NotReady


def run(oven, key, values=None, operator=False):
    heard = []
    found = oven.run_test(key, values or {}, heard.append, operator=operator)
    return found, heard


def statuses(found):
    return [(one.step, one.status) for one in found.outcomes]


def test_steps_run_in_order_and_the_end_runs_last(oven):
    found, _ = run(oven, "heat.Preheat", {"celsius": "180"})

    assert statuses(found) == [
        ("Write setpoint", PASSED),
        ("Wait for the probe", PASSED),
        ("Element off", PASSED),
    ]
    assert found.outcomes[-1].end
    assert found.verdict is PASSED
    assert oven.handle().sent == ["set 180", "set 0"]


def test_a_step_s_report_becomes_its_detail(oven):
    found, _ = run(oven, "heat.Preheat", {"celsius": "180"})

    assert found.outcomes[0].detail == "asked for 180 C"


def test_a_measurement_outside_its_limits_fails_the_step(oven):
    oven.drift = 12

    found, _ = run(oven, "heat.Preheat", {"celsius": "180"})

    probe = found.outcomes[1]
    assert probe.status is FAILED
    assert probe.measurements[0].value == 192
    assert "probe 192 outside 175 to 185" in probe.detail
    assert found.outcomes[2].status is PASSED


def test_the_first_failure_stops_the_steps_but_not_the_end(oven):
    found, _ = run(oven, "heat.Breaks")

    assert statuses(found) == [
        ("First", FAILED),
        ("Second", SKIPPED),
        ("Off", PASSED),
    ]
    assert found.outcomes[0].detail == "RuntimeError: the element is open circuit"
    assert found.outcomes[1].skipped is SkipReason.NOT_REACHED


def test_a_step_may_fail_and_let_the_next_one_run(oven):
    found, _ = run(oven, "heat.Carries")

    assert statuses(found) == [("First", FAILED), ("Second", WARNED)]
    assert found.verdict is FAILED


def test_finishing_skips_what_is_left_as_not_needed(oven):
    found, _ = run(oven, "heat.Finishes")

    assert statuses(found) == [("Look", PASSED), ("Heat", SKIPPED)]
    assert found.outcomes[0].detail == "already hot"
    assert found.outcomes[1].skipped is SkipReason.NOT_NEEDED


def test_skipping_one_step_lets_the_next_run(oven):
    found, _ = run(oven, "heat.Skips")

    assert statuses(found) == [("Maybe", SKIPPED), ("Always", PASSED)]
    assert found.outcomes[0].skipped is SkipReason.NOT_NEEDED


def test_an_end_that_raises_is_an_error_and_the_worst_verdict(oven):
    found, _ = run(oven, "heat.EndsBadly")

    assert statuses(found) == [("Heat", PASSED), ("Off", ERROR)]
    assert found.verdict is ERROR


def test_steps_from_a_base_class_come_first(oven):
    found, _ = run(oven, "heat.Holds")

    assert statuses(found) == [
        ("Identify", PASSED),
        ("Element on", PASSED),
        ("Hold", FAILED),
        ("Element off", PASSED),
    ]


def test_every_outcome_is_reported_as_it_settles(oven):
    found, heard = run(oven, "heat.Breaks")

    assert heard == list(found.outcomes)


def test_a_test_does_not_start_while_its_link_is_down(oven):
    oven.disconnect()

    with pytest.raises(NotReady, match="not connected"):
        run(oven, "heat.Preheat", {"celsius": "180"})


def test_a_test_that_needs_the_port_does_not_start_while_the_link_holds_it(oven):
    with pytest.raises(NotReady, match="disconnect first"):
        run(oven, "heat.Unplugged")


def test_a_guard_s_refusal_is_the_reason_it_does_not_start(oven):
    assert oven.readiness("heat.Guarded").reason == "the element is hot"
    with pytest.raises(NotReady, match="the element is hot"):
        run(oven, "heat.Guarded")


# ── While it runs ────────────────────────────────────────────────────────────


def in_background(oven, key, operator=False):
    heard: list = []
    done: dict = {}

    def go():
        done["run"] = oven.run_test(key, {}, heard.append, operator=operator)

    worker = threading.Thread(target=go)
    worker.start()
    return worker, heard, done


def wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_cancelling_cancels_the_step_skips_the_rest_and_runs_the_end(oven):
    heat.Waits.started.clear()
    worker, _, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    oven.cancel()
    worker.join(5)

    assert statuses(done["run"]) == [
        ("Wait", CANCELLED),
        ("After", SKIPPED),
        ("Off", PASSED),
    ]
    assert done["run"].outcomes[1].skipped is SkipReason.CANCELLED


def test_nothing_else_runs_while_a_test_is_running(oven):
    heat.Waits.started.clear()
    worker, _, _ = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    assert oven.readiness("heat.Preheat").reason == "a test is running"
    assert oven.readiness("calls.set_element").reason == "a test is running"
    oven.cancel()
    worker.join(5)


def test_disconnecting_cancels_the_running_test_first(oven):
    heat.Waits.started.clear()
    worker, _, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    oven.disconnect()
    worker.join(5)

    assert done["run"].outcomes[-1].step == "Off"
    assert oven.stopped == 1


# ── Asking the operator ──────────────────────────────────────────────────────


def prompts(heard):
    return [one for one in heard if isinstance(one, Prompt)]


def test_a_test_that_asks_needs_an_operator(oven):
    assert oven.readiness("heat.Asks", operator=False).reason == "needs an operator"
    assert oven.readiness("heat.Asks", operator=True)


def test_a_question_waits_for_the_answer_and_records_it(oven):
    worker, heard, done = in_background(oven, "heat.Asks", operator=True)
    wait_for(lambda: len(prompts(heard)) == 1)
    assert prompts(heard)[0].question.hint == "Close the door, then press Continue."
    oven.answer("True")
    wait_for(lambda: len(prompts(heard)) == 2)

    oven.answer("true")
    worker.join(5)

    smell = done["run"].outcomes[1]
    assert smell.status is WARNED
    assert smell.answers == (("smelled", True),)


def test_every_question_says_when_it_stopped_being_asked(oven):
    worker, heard, _ = in_background(oven, "heat.Asks", operator=True)
    wait_for(lambda: len(prompts(heard)) == 1)
    oven.answer("True")
    wait_for(lambda: len(prompts(heard)) == 2)
    oven.answer("true")
    worker.join(5)

    asked_then_closed = [
        type(one).__name__ for one in heard if isinstance(one, Prompt | PromptClosed)
    ]
    assert asked_then_closed == ["Prompt", "PromptClosed", "Prompt", "PromptClosed"]


def test_a_question_nobody_answers_cancels_the_run(oven):
    oven.patience = 0.2
    worker, heard, done = in_background(oven, "heat.Asks", operator=True)
    wait_for(lambda: len(prompts(heard)) == 1)
    oven.answer("True")

    worker.join(5)

    assert done["run"].outcomes[1].status is CANCELLED
    assert done["run"].outcomes[1].detail == "no answer within 0 s"
    assert done["run"].verdict is CANCELLED


def test_cancelling_while_a_question_is_open_ends_the_wait(oven):
    worker, heard, done = in_background(oven, "heat.Asks", operator=True)
    wait_for(lambda: len(prompts(heard)) == 1)

    oven.cancel()
    worker.join(5)

    assert statuses(done["run"])[0] == ("Close", CANCELLED)


def test_answering_when_nothing_is_asked_is_refused(oven):
    with pytest.raises(NotReady):
        oven.answer("yes")


def test_a_run_s_outcomes_are_steps_and_prompts_only(oven):
    _, heard = run(oven, "heat.Breaks")

    assert all(isinstance(one, StepOutcome | Prompt | PromptClosed) for one in heard)


def test_finishing_as_failed_leaves_the_rest_not_reached(oven):
    found, _ = run(oven, "heat.Holds")

    assert found.outcomes[2].detail == "held"
    assert found.outcomes[-1].end


def test_a_run_cancelled_between_steps_is_not_a_pass(oven):
    worker, _, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)
    oven.cancel()
    worker.join(5)

    assert done["run"].cancelled
    assert done["run"].verdict is CANCELLED


def test_a_cancel_during_the_end_step_cuts_nothing_short(oven, monkeypatch):
    def off_then_cancelled(self) -> None:
        self.sub.handle().set_point(0)
        self._run.cancelled.set()

    monkeypatch.setattr(heat.Preheat, "element_off", off_then_cancelled)

    found, _ = run(oven, "heat.Preheat", {"celsius": "180"})

    assert [one.status for one in found.outcomes] == [PASSED, PASSED, PASSED]
    assert not found.cancelled
    assert found.verdict is PASSED


def test_a_run_that_ignores_the_cancel_is_given_up_on_and_said_so(oven, monkeypatch):
    from shared.diagnostics import diagnosable

    ending = heat.Breaks.end_step
    assert ending is not None
    monkeypatch.setattr(
        heat.Breaks, "end_step", dataclasses.replace(ending, expected_s=0.1)
    )
    said = []
    monkeypatch.setattr(
        diagnosable.run_log.log, "warning", lambda text, *args: said.append(args)
    )
    release = threading.Event()

    def deaf(self) -> None:
        release.wait(5)

    monkeypatch.setattr(heat.Breaks, "first", deaf)
    worker, _, _ = in_background(oven, "heat.Breaks")
    wait_for(lambda: oven.running() is not None)

    oven.cancel()

    assert said and said[0][0] == "fixture.heat.Breaks"
    release.set()
    worker.join(5)


# ── Stopping ─────────────────────────────────────────────────────────────────


def test_a_stop_requested_while_idle_stops_at_once(oven):
    assert oven.request_stop() is False
    assert oven.stopped == 1


def test_a_stop_requested_during_a_run_waits_for_the_end_step(oven):
    heat.Waits.started.clear()
    worker, heard, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    assert oven.request_stop() is True
    worker.join(5)

    assert oven.stopped == 1
    assert oven.handle().sent[-2:] == ["set 0", "stop"]
    assert done["run"].stopped is not None
    assert done["run"].stopped.summary == "stopped"
    assert done["run"].stop_requested is not None
    assert heard[-1] == done["run"].stopped


def test_a_deferred_stop_that_fails_says_so(oven, monkeypatch):
    def jammed() -> None:
        raise RuntimeError("element 1 did not confirm")

    monkeypatch.setattr(oven, "stop", jammed)
    heat.Waits.started.clear()
    worker, _, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    oven.request_stop()
    worker.join(5)

    assert done["run"].stopped is not None
    assert "element 1 did not confirm" in done["run"].stopped.summary


def test_a_run_says_it_is_registered_before_its_first_step(oven):
    registered = []

    def started():
        registered.append(oven.running() is not None)

    oven.run_test(
        "heat.Preheat", {"celsius": "180"}, lambda record: None, on_started=started
    )

    assert registered == [True]


def test_a_stop_with_the_link_down_raises_and_sends_nothing(oven):
    oven.disconnect()
    before = oven.stopped

    with pytest.raises(StopUnconfirmed, match="not sent: the link is down"):
        oven.request_stop()

    assert oven.stopped == before


def test_a_deferred_stop_after_the_link_died_is_unconfirmed(oven, monkeypatch):
    heat.Waits.started.clear()
    worker, heard, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    monkeypatch.setattr(oven, "_alive", lambda handle: False)
    oven.request_stop()
    worker.join(5)

    finished = done["run"]
    assert oven.stopped == 0
    assert finished.stopped.level is Level.ERROR
    assert "the hardware's state is unknown" in finished.stopped.summary
    assert finished.stop_unconfirmed == finished.stopped.summary
    assert heard[-1] == finished.stopped


def test_a_link_lost_during_a_run_is_unconfirmed_without_a_stop(oven, monkeypatch):
    heat.Waits.started.clear()
    worker, _, done = in_background(oven, "heat.Waits")
    heat.Waits.started.wait(5)

    monkeypatch.setattr(oven, "_alive", lambda handle: False)
    oven.cancel()
    worker.join(5)

    finished = done["run"]
    assert finished.stop_requested is None
    assert "lost while the test ran" in (finished.stop_unconfirmed or "")


def test_a_stop_for_a_test_that_holds_the_port_says_the_subsystem_cannot_reach_it():
    unconfirmed = StopUnconfirmed(LinkState.DOWN, port_held_by_test=True)

    assert "opened the port itself" in str(unconfirmed)


def test_an_end_step_states_how_long_it_is_expected_to_take():
    assert heat.Preheat.ends_within_s() == 30.0

    class Quick(heat.Preheat):
        @end("Element off", expected_s=5)
        def element_off(self) -> None:
            pass

    assert Quick.ends_within_s() == 5
