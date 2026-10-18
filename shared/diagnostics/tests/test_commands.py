import pytest

from shared.subsystem import Level, NotReady


def test_a_command_converts_its_values_and_returns_its_reply(oven):
    reply = oven.run_command("calls.set_element", {"celsius": "90"})

    assert reply.summary == "set to 90 C"
    assert oven.handle().setpoint == 90


def test_a_command_leaves_the_hardware_as_it_was_asked(oven):
    oven.run_command("calls.set_element", {"celsius": "90"})

    assert oven.handle().sent == ["set 90"]
    assert oven.stopped == 0


def test_the_reply_is_kept_as_the_command_s_last_result(oven):
    reply = oven.run_command("calls.set_element", {"celsius": "90"})

    assert oven.last_reply("calls.set_element") is reply


def test_a_command_that_raises_replies_with_an_error(oven):
    reply = oven.run_command("calls.broken", {})

    assert reply.level is Level.ERROR
    assert reply.summary == "OSError: no reply"


def test_a_command_does_not_run_while_the_link_is_down(oven):
    oven.disconnect()

    with pytest.raises(NotReady, match="not connected"):
        oven.run_command("calls.set_element", {"celsius": "90"})
