"""GuiModel driven against the demo subsystem, which acts out every behaviour without hardware."""

import json
import threading

import pytest

from demo import board as demo_board
from demo.bench import link as demo_link
from gui.src.messages import Change, Channel, RequestFinished, SubsystemChanged
from gui.src.model import GuiModel, Refused
from shared.diagnostics import as_json
from shared.subsystem import LinkState

WAIT_S = 5.0


class ChangeRecorder:
    """Every change a model published, and a way to wait for one without polling."""

    def __init__(self) -> None:
        self.changes: list[Change] = []
        self._condition = threading.Condition()

    def __call__(self, change: Change) -> None:
        with self._condition:
            self.changes.append(change)
            self._condition.notify_all()

    def wait_for(self, matches, timeout: float = WAIT_S) -> Change:
        with self._condition:
            found = self._condition.wait_for(
                lambda: next((one for one in self.changes if matches(one)), None),
                timeout,
            )
        assert found, "the change never came"
        return found


@pytest.fixture(autouse=True)
def demo_without_pauses(monkeypatch):
    monkeypatch.setattr(demo_link, "PACE_S", 0.0)


@pytest.fixture
def model():
    started = GuiModel(roster=("demo",))
    started.start()
    yield started
    started.close()


@pytest.fixture
def recorder(model):
    heard = ChangeRecorder()
    model.subscribe(heard)
    return heard


def link_state(model) -> LinkState:
    view = model.subsystem_view("demo")
    assert view.link is not None
    return view.link.state


def test_connecting_publishes_the_link_going_up(model, recorder):
    model.connect("demo", demo_board.HEALTHY)

    recorder.wait_for(lambda one: one.channel is Channel.LINK)
    assert link_state(model) is LinkState.UP
    assert model.subsystem_view("demo").facts is not None


def test_a_board_that_dies_is_published_without_any_request(
    model, recorder, monkeypatch
):
    monkeypatch.setattr("demo.subsystem.DIES_AFTER_S", 0.05)
    model.connect("demo", demo_board.DIES)
    recorder.changes.clear()

    recorder.wait_for(
        lambda one: one.channel is Channel.LINK and link_state(model) is LinkState.ERROR
    )


def test_a_refused_connect_is_one_sentence(model):
    with pytest.raises(Refused, match="refuses to connect"):
        model.connect("demo", demo_board.REFUSES)


def test_a_test_reports_every_step_then_its_end(model, recorder):
    model.connect("demo", demo_board.HEALTHY)

    model.start_test("demo", "outcomes.Passes", {})
    ended = recorder.wait_for(
        lambda one: one.channel is Channel.TEST_PROGRESS and one.test_ended
    )

    assert ended.test_key == "outcomes.Passes"
    last = model.test_view("demo", "outcomes.Passes").last
    assert last is not None and last.verdict is not None
    assert last.verdict.value == "passed"
    assert [one.step for one in last.outcomes] == ["Greet", "Read", "Measure"]


def test_the_focus_is_held_until_the_test_ends(model, recorder):
    model.connect("demo", demo_board.HEALTHY)

    model.start_test("demo", "running.RunsLong", {"seconds": "30"})
    assert model.focus[1] == "demo.running.RunsLong"
    with pytest.raises(Refused, match="busy with demo.running.RunsLong"):
        model.call_command("demo", "calls.read_temperature", {})

    model.request_stop("demo")
    recorder.wait_for(lambda one: one.test_ended)
    assert model.focus == (None, None)


def test_a_stopped_test_is_cancelled_and_still_runs_its_end_step(model, recorder):
    model.connect("demo", demo_board.HEALTHY)
    model.start_test("demo", "running.RunsLong", {"seconds": "30"})

    assert model.request_stop("demo") is True
    recorder.wait_for(lambda one: one.test_ended)

    last = model.test_view("demo", "running.RunsLong").last
    assert last is not None and last.verdict is not None
    assert last.verdict.value == "cancelled"
    assert last.outcomes[-1].end and last.outcomes[-1].status.value == "passed"
    assert last.stopped is not None and last.stopped.summary == "stopped"


def test_a_question_is_answered_through_the_model(model, recorder):
    model.connect("demo", demo_board.HEALTHY)
    model.start_test("demo", "asking.Asks", {})

    def asked() -> bool:
        last = model.test_view("demo", "asking.Asks").last
        return last is not None and last.prompt is not None

    recorder.wait_for(lambda one: asked())
    model.answer_question("demo", "true")
    recorder.wait_for(
        lambda one: (
            (last := model.test_view("demo", "asking.Asks").last) is not None
            and len(last.outcomes) == 1
        )
    )
    model.request_stop("demo")
    recorder.wait_for(lambda one: one.test_ended)


def test_a_stop_with_the_link_down_raises_an_alarm(model, recorder):
    with pytest.raises(Refused, match="not sent"):
        model.request_stop("demo")

    alarm = model.stop_alarm("demo")
    assert alarm is not None and "the hardware's state is unknown" in alarm.message
    model.acknowledge_stop_alarm("demo")
    assert model.stop_alarm("demo") is None


def test_a_board_that_dies_during_a_hazardous_test_raises_a_hazardous_alarm(
    model, recorder, monkeypatch
):
    monkeypatch.setattr(demo_link, "PACE_S", 0.1)
    monkeypatch.setattr("demo.subsystem.DIES_AFTER_S", 0.15)
    model.connect("demo", demo_board.DIES)

    model.start_test("demo", "running.Hazardous", {"velocity": "5000"})
    recorder.wait_for(lambda one: one.test_ended, timeout=10.0)

    last = model.test_view("demo", "running.Hazardous").last
    assert last is not None and last.stop_unconfirmed
    alarm = model.stop_alarm("demo")
    assert alarm is not None and alarm.hazardous


def test_a_jammed_drive_is_reported_and_never_called_stopped(model):
    model.connect("demo", demo_board.HEALTHY)
    model.call_command("demo", "calls.jam", {"drive": "left", "jammed": "true"})

    with pytest.raises(Refused, match="jammed"):
        model.request_stop("demo")

    model.call_command("demo", "calls.jam", {"drive": "left", "jammed": "false"})


def test_closing_disconnects_every_subsystem(recorder, model):
    model.connect("demo", demo_board.HEALTHY)

    model.close()

    assert link_state(model) is LinkState.DOWN


def test_every_event_a_worker_sends_survives_json(model):
    model.connect("demo", demo_board.HEALTHY)
    view = model.subsystem_view("demo")

    for event in (
        SubsystemChanged(view, True),
        RequestFinished(
            "demo", 1, model.call_command("demo", "calls.read_temperature", {})
        ),
    ):
        packed = as_json(event)
        assert json.loads(json.dumps(packed)) == packed
