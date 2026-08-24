import pytest

from machine import AREAS, Activity, Area, Busy, Machine


def test_nothing_is_gated_while_the_machine_is_idle():
    stef = Machine(roster=())

    assert stef.activity is None


def test_an_activity_is_the_one_the_machine_reports():
    stef = Machine(roster=())

    with stef.focusing_on(Activity.SCANNING):
        assert stef.activity is Activity.SCANNING


def test_the_machine_is_released_however_the_activity_ends():
    stef = Machine(roster=())

    with pytest.raises(RuntimeError):
        with stef.focusing_on(Activity.BENCHING):
            raise RuntimeError("boom")

    assert stef.activity is None


def test_a_second_activity_is_refused_rather_than_queued():
    stef = Machine(roster=())

    with stef.focusing_on(Activity.BENCHING):
        with pytest.raises(Busy) as refused:
            stef.focus_on(Activity.SCANNING)

    assert refused.value.activity is Activity.BENCHING


def test_configuring_holds_the_machine_like_any_other_activity():
    stef = Machine(roster=())

    with stef.focusing_on(Activity.CONFIGURING):
        with pytest.raises(Busy):
            stef.focus_on(Activity.BENCHING)


def test_every_area_answers_to_exactly_one_activity():
    assert set(AREAS) == set(Area)
    assert set(AREAS.values()) == set(Activity)
