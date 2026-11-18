"""What the transport subsystem declares, read and refused through GuiModel, with nothing plugged in."""

import json

import pytest

from gui.src.model import GuiModel, Refused
from shared.diagnostics import as_json
from shared.subsystem import LinkState


@pytest.fixture
def unplugged(monkeypatch):
    """Answer as a machine with nothing attached, so every refusal reads the same anywhere."""
    from transport import fw

    monkeypatch.setattr(fw.probe, "candidates", lambda: ())


@pytest.fixture
def model(unplugged):
    started = GuiModel(roster=("transport",))
    started.start()
    yield started
    started.close()


def command_named(model, command_key):
    return next(
        one
        for one in model.subsystem_view("transport").commands
        if one.key == command_key
    )


def test_the_port_list_is_asked_for_and_offers_auto_first(model):
    port = model.subsystem_view("transport").link.target
    assert port.options is None
    assert port.reload == ("transport", "link", "port")

    offered = model.options("transport", "link", "port")
    assert offered[0]["value"] == "auto"
    assert all("value" in one and "label" in one for one in offered)


def test_options_nobody_declared_are_a_key_error(model):
    with pytest.raises(KeyError):
        model.options("transport", "link", "nope")


def test_a_derived_form_keeps_the_shape_the_firmware_declared(model):
    write = command_named(model, "raw.write")
    ops = next(one for one in write.inputs if one.kind == "group")
    assert {column.name for column in ops.columns} == {"reg", "value"}
    assert (write.group, write.name, write.hazard) == (
        "raw",
        "write",
        "writes driver registers",
    )


def test_a_test_carries_its_steps_and_its_end(model):
    one_turn = next(
        one
        for one in model.subsystem_view("transport").tests
        if one.key == "spin.OneTurn"
    )
    assert one_turn.hazardous
    assert one_turn.steps[0].title == "Identify"
    assert one_turn.end is not None and one_turn.end.title == "At rest"


def test_nothing_on_the_board_is_spelled_in_ctypes(model):
    packed = as_json(model.subsystem_view("transport"))
    assert json.loads(json.dumps(packed)) == packed


def test_connecting_with_nothing_plugged_in_is_refused_with_the_probe_s_sentence(model):
    readiness = model.probe_target("transport", "auto")
    assert not readiness and readiness.reason


def test_a_call_on_a_link_that_is_down_is_refused_by_its_precondition(model):
    with pytest.raises(Refused, match="not connected"):
        model.call_command("transport", "sys.version", {})


def test_a_call_nobody_declared_is_refused(model):
    with pytest.raises(Refused):
        model.call_command("transport", "no.such", {})


def test_a_test_that_opens_the_port_is_refused_while_the_link_holds_it(
    model, monkeypatch
):
    transport = model.machine.subsystem("transport")
    monkeypatch.setattr(transport, "link_state", lambda: LinkState.UP)

    with pytest.raises(Refused, match="disconnect first"):
        model.start_test("transport", "prelink.VerifyPort", {"port": "auto"})
    assert model.focus == (None, None)


def test_a_run_with_nothing_plugged_in_fails_its_first_step_and_skips_the_rest(model):
    from gui.tests.test_model import ChangeRecorder

    recorder = ChangeRecorder()
    model.subscribe(recorder)
    model.start_test("transport", "prelink.VerifyPort", {"port": "auto"})
    recorder.wait_for(lambda one: one.test_ended)

    last = model.test_view("transport", "prelink.VerifyPort").last
    assert last is not None
    assert [one.status.value for one in last.outcomes] == [
        "failed",
        "skipped",
        "skipped",
    ]
    assert [one.skipped.value for one in last.outcomes[1:] if one.skipped] == [
        "not_reached",
        "not_reached",
    ]
