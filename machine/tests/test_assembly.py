import json

import pytest

from machine import Machine, assembled
from shared.diagnostics import as_json
from shared.subsystem import LinkState

FIXTURE_PACKAGE = "machine.tests.fixture"


def test_a_package_is_assembled_into_one_addressable_subsystem(hotplate):
    assert hotplate.id == "fixture"
    assert hotplate.summary.startswith("A hotplate on a dial")
    assert hotplate.config.package == FIXTURE_PACKAGE
    assert [one.key for one in hotplate.tests] == ["routines.Warm"]


def test_a_package_that_exports_no_subsystem_is_not_assembled():
    with pytest.raises(ImportError, match="exports no SUBSYSTEM"):
        assembled("machine.tests.fixture.routines")


def test_a_subsystem_is_down_until_it_is_connected(hotplate):
    assert hotplate.link_state() is LinkState.DOWN


def test_a_connected_subsystem_is_up(plugged_in):
    assert plugged_in.link_state() is LinkState.UP


def test_a_whole_subsystem_survives_being_json(hotplate):
    packed = as_json(hotplate.view())

    assert json.dumps(packed)
    assert packed["id"] == "fixture"
    assert packed["link"]["state"] == "down"


def test_the_machine_skips_a_package_it_cannot_assemble():
    stef = Machine(roster=(FIXTURE_PACKAGE, "machine.no_such_package"))

    stef.assemble()

    assert list(stef.subsystems) == [FIXTURE_PACKAGE]
    assert stef.link_state_of("machine.no_such_package") is LinkState.DOWN


def test_the_demo_board_joins_the_roster_only_while_its_flag_is_set(monkeypatch):
    from machine import DEMO, DEMO_FLAG, ROSTER, default_roster

    monkeypatch.delenv(DEMO_FLAG, raising=False)
    assert default_roster() == ROSTER

    monkeypatch.setenv(DEMO_FLAG, "1")
    assert default_roster() == (*ROSTER, DEMO)
    assert Machine().roster[-1] == DEMO
