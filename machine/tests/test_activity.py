import pytest

from machine import AREAS, Activity, Area, Busy, Machine


def test_nothing_is_gated_while_the_machine_is_idle():
    machine = Machine(roster=())

    assert machine.activity is None


def test_an_activity_is_the_one_the_machine_reports():
    machine = Machine(roster=())

    with machine.focusing_on(Activity.SCANNING, "scan"):
        assert machine.activity is Activity.SCANNING


def test_the_machine_is_released_however_the_activity_ends():
    machine = Machine(roster=())

    with pytest.raises(RuntimeError):
        with machine.focusing_on(Activity.BENCHING, "transport.spin.OneTurn"):
            raise RuntimeError("boom")

    assert machine.activity is None


def test_a_second_activity_is_refused_rather_than_queued():
    machine = Machine(roster=())

    with machine.focusing_on(Activity.BENCHING, "transport.spin.OneTurn"):
        with pytest.raises(Busy) as refused:
            machine.focus_on(Activity.SCANNING, "scan")

    assert refused.value.activity is Activity.BENCHING
    assert refused.value.holder == "transport.spin.OneTurn"
    assert "transport.spin.OneTurn" in str(refused.value)


def test_configuring_holds_the_machine_like_any_other_activity():
    machine = Machine(roster=())

    with machine.focusing_on(Activity.CONFIGURING, "settings"):
        with pytest.raises(Busy):
            machine.focus_on(Activity.BENCHING, "transport.raw.write")


def test_the_holder_is_known_while_focused_and_forgotten_after():
    machine = Machine(roster=())

    with machine.focusing_on(Activity.BENCHING, "demo.calls.enable"):
        assert machine.focus_holder == "demo.calls.enable"

    assert machine.focus_holder is None


def test_every_area_answers_to_exactly_one_activity():
    assert set(AREAS) == set(Area)
    assert set(AREAS.values()) == set(Activity)
