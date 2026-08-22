import pytest

from shared import bench_api
from shared.bench_api import CALL, LINK, PRELINK, SETUP, SubsystemState
from shared.bench_api.tests.fixture import state

FIXTURE = "shared.bench_api.tests.fixture"


# ── A package is the subsystem ───────────────────────────────────────────────


def test_the_package_name_is_the_id_and_its_docstring_is_the_prose(oven):
    assert oven.id == "fixture"
    assert oven.spec.summary.startswith("An oven with a thermocouple")
    assert "One heating element" in oven.spec.description


def test_the_package_answers_for_its_own_state(oven):
    assert state() is SubsystemState.DOWN


def test_every_module_under_the_package_declared_into_it(oven):
    assert "routines.ramp" in oven.routines
    assert "generated.ramp_once" in oven.routines


def test_a_routine_is_named_for_where_it_was_written(oven):
    assert oven.routines["routines.ramp"].id == "fixture.routines.ramp"
    assert oven.routines["routines.ramp"].group == "routines"


def test_a_docstring_becomes_a_title_without_its_full_stop(oven):
    declared = oven.routines["routines.ramp"]
    assert declared.title == "Ramp the oven"
    assert declared.description.startswith("Warms it, holds it")


def test_a_routine_declared_from_parts_lands_beside_the_decorated_ones(oven):
    assert oven.routines["generated.ramp_once"].title == "Ramp once"
    assert oven.routines["generated.ramp_once"].hazardous


def test_a_second_routine_by_one_name_is_refused(oven):
    with pytest.raises(bench_api.DeclarationError, match="two routines"):
        bench_api.register_routine(
            module=f"{FIXTURE}.routines",
            group="routines",
            name="ramp",
            title="Ramp again",
            run=lambda values: iter(()),
        )


def test_a_routine_declared_under_no_loaded_package_is_refused(oven):
    with pytest.raises(
        bench_api.DeclarationError, match="declares against no subsystem"
    ):
        bench_api.register_routine(
            module="nobody.owns.this",
            group="stray",
            name="ramp",
            title="Ramp",
            run=lambda values: iter(()),
        )


def test_a_test_module_under_the_package_is_not_walked_for_declarations(oven):
    assert not any(r.group.startswith("test_") for r in oven.routines.values())


# ── What the category gates ──────────────────────────────────────────────────


def test_a_routine_needing_a_link_is_blocked_while_there_is_none(oven):
    verdict = bench_api.readiness_of(oven.routines["routines.ramp"], state())

    assert not verdict
    assert verdict.reason == "not connected"


def test_the_same_routine_is_ready_once_the_link_is_up(linked):
    assert bench_api.readiness_of(linked.routines["routines.ramp"], state())


def test_a_prelink_routine_is_blocked_while_the_link_holds_the_port(linked):
    verdict = bench_api.readiness_of(linked.routines["routines.check_probe"], state())

    assert not verdict
    assert "disconnect first" in str(verdict)


def test_a_prelink_routine_is_ready_when_nothing_holds_the_port(oven):
    assert bench_api.readiness_of(oven.routines["routines.check_probe"], state())


def test_connecting_is_refused_once_something_is_already_connected(linked):
    declared = linked.routines["routines.connect"]

    assert bench_api.readiness_of(declared, state())


def test_every_category_is_one_state_read(oven):
    kinds = {r.category for r in oven.routines.values()}

    assert kinds == {LINK, PRELINK, SETUP, CALL} - {CALL}


# ── Asking with the values in hand ───────────────────────────────────────────


def test_a_value_dependent_guard_answers_for_the_values_it_was_given(oven):
    declared = oven.routines["routines.connect"]

    assert bench_api.readiness_with(declared, {"port": "/dev/oven0"})
    assert not bench_api.readiness_with(declared, {"port": "/dev/other"})


def test_a_routine_with_no_such_guard_is_always_ready_to_be_asked(oven):
    assert bench_api.readiness_with(oven.routines["routines.ramp"], {})
