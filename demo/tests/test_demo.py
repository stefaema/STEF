import threading
import time

import pytest

import demo
from demo import board as boards
from demo.bench import asking
from shared.diagnostics import CANCELLED, ERROR, FAILED, PASSED, SKIPPED, WARNED, Prompt
from shared.subsystem import LinkState, NotReady


def run(sub, key, values=None, operator=False):
    return sub.run_test(key, values or {}, lambda said: None, operator=operator)


def statuses(found):
    return [one.status for one in found.outcomes]


@pytest.mark.parametrize(
    ("key", "verdict"),
    [
        ("outcomes.Passes", PASSED),
        ("outcomes.Warns", WARNED),
        ("outcomes.FailsEarly", FAILED),
        ("outcomes.CarriesOn", FAILED),
        ("outcomes.OutOfLimits", FAILED),
        ("outcomes.FinishesEarly", PASSED),
        ("outcomes.SkipsOne", PASSED),
        ("outcomes.EndsBadly", ERROR),
        ("running.Hazardous", PASSED),
    ],
)
def test_each_test_ends_the_way_its_name_says(board, key, verdict):
    assert run(board, key).verdict is verdict


def test_failing_early_leaves_the_rest_not_reached(board):
    assert statuses(run(board, "outcomes.FailsEarly")) == [FAILED, SKIPPED, SKIPPED]


def test_the_guarded_test_waits_for_the_left_drive(board):
    assert board.readiness("outcomes.Guarded").reason == "enable the left drive first"

    board.run_command("calls.enable", {"drive": "left", "on": "true"})

    assert board.readiness("outcomes.Guarded")


def test_the_hazardous_test_leaves_the_drive_at_rest(board):
    run(board, "running.Hazardous", {"velocity": "100"})

    left = board.board().drive("left")
    assert (left.enabled, left.velocity) == (False, 0)


def test_a_jammed_drive_turns_the_end_step_into_an_error(board):
    board.run_command("calls.jam", {"drive": "left", "jammed": "true"})

    assert run(board, "running.Hazardous").verdict is ERROR
    board.run_command("calls.jam", {"drive": "left", "jammed": "false"})


def test_stopping_names_a_jammed_drive(board):
    board.run_command("calls.enable", {"drive": "right", "on": "true"})
    board.run_command("calls.jam", {"drive": "left", "jammed": "true"})

    with pytest.raises(RuntimeError, match="left: jammed"):
        board.stop()

    assert not board.board().drive("right").enabled
    board.run_command("calls.jam", {"drive": "left", "jammed": "false"})


def test_the_port_test_runs_only_while_nothing_is_connected(board):
    assert not board.readiness("port.NeedsThePort")

    board.disconnect()

    assert run(board, "port.NeedsThePort").verdict is PASSED
    board.connect("healthy")


def test_a_long_run_is_cancelled_and_still_tidies_up(board):
    done = {}
    worker = threading.Thread(
        target=lambda: done.setdefault(
            "run", run(board, "running.RunsLong", {"seconds": "60"})
        )
    )
    worker.start()
    while board.running() is None:
        time.sleep(0.01)
    time.sleep(0.2)

    board.cancel()
    worker.join(5)

    assert statuses(done["run"]) == [CANCELLED, SKIPPED, PASSED]


def test_every_question_is_asked_and_answered(board, monkeypatch):
    monkeypatch.setattr(asking, "PATIENCE_S", 5.0)
    answers = iter(["True", "true", "green", "false"])
    heard = []

    def answer(said):
        heard.append(said)
        if isinstance(said, Prompt):
            threading.Timer(0.05, lambda: board.answer(next(answers))).start()

    found = board.run_test("asking.Asks", {}, answer, operator=True)

    assert found.verdict is PASSED
    assert found.outcomes[2].detail == "the operator chose green"


def test_asking_needs_an_operator(board):
    assert board.readiness("asking.Asks", operator=False).reason == "needs an operator"


def test_a_board_that_refuses_keeps_the_link_down():
    sub = demo.SUBSYSTEM(demo)

    with pytest.raises(NotReady, match="refuses"):
        sub.connect(boards.REFUSES)

    assert sub.link_state() is LinkState.DOWN


def test_a_board_that_fails_to_open_is_an_error():
    sub = demo.SUBSYSTEM(demo)

    with pytest.raises(OSError):
        sub.connect(boards.FAILS_TO_OPEN)

    assert sub.link_state() is LinkState.ERROR


def test_a_board_that_dies_turns_the_link_to_an_error(monkeypatch):
    monkeypatch.setattr("demo.subsystem.DIES_AFTER_S", 0.05)
    sub = demo.SUBSYSTEM(demo)
    sub.connect(boards.DIES)
    assert sub.link_state() is LinkState.UP

    time.sleep(0.1)

    assert sub.link_state() is LinkState.ERROR
    assert sub.link_reason() == "the connection stopped answering"
    sub.disconnect()


def test_a_command_that_raises_replies_with_an_error(board):
    assert board.run_command("calls.raises", {}).summary.startswith("OSError")


def test_a_group_input_arrives_as_rows(board):
    reply = board.run_command(
        "calls.echo_rows", {"rows": [{"drive": "left", "velocity": "10"}]}
    )

    assert reply.table is not None
    assert reply.table.rows == (("left", "10"),)


def test_the_facts_describe_the_board(board):
    assert board.facts() is not None
    assert dict(board.facts().fields)["drives"] == "left, right"


def test_stopping_during_a_step_that_never_checks_is_still_not_a_pass(
    board, monkeypatch
):
    from demo.bench import link
    from shared.diagnostics import SkipReason

    monkeypatch.setattr(link, "PACE_S", 0.3)
    done = {}
    worker = threading.Thread(
        target=lambda: done.setdefault("run", run(board, "outcomes.Passes"))
    )
    worker.start()
    while board.running() is None:
        time.sleep(0.01)
    time.sleep(0.1)

    board.cancel()
    worker.join(5)

    found = done["run"]
    assert statuses(found) == [PASSED, SKIPPED, SKIPPED]
    assert found.outcomes[1].skipped is SkipReason.CANCELLED
    assert found.cancelled
    assert found.verdict is CANCELLED
