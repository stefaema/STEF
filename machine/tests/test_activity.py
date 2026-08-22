import pytest

from machine import Activity, Busy, Machine


def test_nothing_is_gated_while_the_machine_is_idle():
    stef = Machine(roster=())

    assert stef.activity is Activity.IDLE
    assert stef.openings() == {"bench": None, "scan": None, "config": None}


def test_an_activity_leaves_its_own_area_open_and_closes_the_others():
    stef = Machine(roster=())

    with stef.doing(Activity.SCANNING, "transport.forward_film", "A scan is running."):
        assert stef.may_open("scan")
        assert not stef.may_open("bench")
        assert stef.blocked_reason("config") == "A scan is running."


def test_the_machine_is_released_however_the_activity_ends():
    stef = Machine(roster=())

    with pytest.raises(RuntimeError):
        with stef.doing(Activity.BENCHING, "transport.flash_board", "Flashing."):
            raise RuntimeError("boom")

    assert stef.activity is Activity.IDLE
    assert stef.busy_with is None


def test_a_second_holder_is_refused_rather_than_queued():
    stef = Machine(roster=())

    with stef.doing(
        Activity.BENCHING, "transport.flash_board", "The board is being flashed."
    ):
        with pytest.raises(Busy, match="The board is being flashed."):
            stef.take(Activity.SCANNING, "transport.forward_film", "A scan is running.")


def test_configuring_holds_the_machine_like_any_other_activity():
    stef = Machine(roster=())

    with stef.doing(
        Activity.CONFIGURING,
        "config.transport",
        "Unsaved changes in the transport settings.",
    ):
        assert stef.may_open("config")
        assert not stef.may_open("bench")
        assert not stef.may_open("scan")


def test_the_taker_states_the_sentence_the_next_comer_is_told():
    stef = Machine(roster=())

    stef.take(
        Activity.CONFIGURING,
        "config.transport",
        "Unsaved changes in the transport settings.",
    )

    assert stef.blocked_reason("bench") == "Unsaved changes in the transport settings."
    assert stef.busy_with == "config.transport"
