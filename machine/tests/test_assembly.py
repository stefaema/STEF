import json

from machine import subsystem_json
from shared.subsystem import SubsystemState

FIXTURE_PACKAGE = "machine.tests.fixture"


def test_a_package_is_assembled_into_one_addressable_subsystem(hotplate):
    assert hotplate.spec.id == "fixture"
    assert hotplate.spec.summary.startswith("A hotplate on a dial")
    assert hotplate.config.package == FIXTURE_PACKAGE
    assert "routines.warm" in hotplate.bench.routines


def test_the_state_is_read_off_the_package_every_time_it_is_asked(hotplate):
    assert hotplate.state is SubsystemState.DOWN


def test_a_package_that_reports_differently_later_is_believed(plugged_in):
    assert plugged_in.state is SubsystemState.UP


def test_a_whole_subsystem_survives_being_json(hotplate):
    assert json.dumps(subsystem_json(hotplate))


def test_the_name_a_subsystem_is_known_by_reaches_the_screen(hotplate):
    assert subsystem_json(hotplate)["id"] == "fixture"


def test_the_state_is_read_once_for_the_whole_subsystem(hotplate):
    packed = subsystem_json(hotplate)

    assert packed["state"] == "down"
    assert all(one["ready"]["reason"] != "" for one in packed["routines"])
