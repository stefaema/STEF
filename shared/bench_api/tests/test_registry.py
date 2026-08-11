"""What the decorators register, how a run yields, and what fails at import."""

import dataclasses

import pytest

from shared import bench_api
from shared.bench_api import DeclarationError, StepStatus
from shared.bench_api.params import current_options

# ── What got declared ────────────────────────────────────────────────────────


def test_a_subsystem_carries_its_id_and_its_prose(rig):
    assert rig.id == "rig"
    assert rig.description.startswith("One pretend board.")
    # cleandoc, so the indentation the decorator was written with is gone.
    assert "\n    " not in rig.description


def test_a_link_carries_its_form_and_finds_its_own_subsystem(rig):
    assert rig.link is not None
    assert rig.link.subsystem == "rig"
    assert [p["name"] for p in rig.link.params] == ["port"]


def test_a_bench_test_takes_its_id_from_its_own_name(rig):
    assert set(rig.bench_tests) == {
        "general",
        "ramp",
        "sweep",
        "otp",
        "reflash",
        "probe",
        "identify_board",
    }
    assert rig.bench_tests["identify_board"].qualified == "rig.identify_board"


def test_title_and_description_come_from_the_docstring(rig):
    ramp = rig.bench_tests["ramp"]
    assert ramp.title == "Acceleration ramp"
    assert ramp.description.startswith("Emits a profile")


def test_steps_are_collected_in_the_order_they_were_defined(rig):
    assert [s.name for s in rig.bench_tests["ramp"].steps] == [
        "enable",
        "run",
        "counted",
    ]
    assert [s.title for s in rig.bench_tests["general"].steps] == [
        "Protocol version",
        "Firmware state",
        "Board table",
    ]


def test_hazard_is_carried_from_the_decorator(rig):
    assert rig.bench_tests["ramp"].hazardous
    assert not rig.bench_tests["general"].hazardous
    assert rig.actions["raw.move"].hazardous
    assert not rig.actions["raw.read"].hazardous


# ── Running one ──────────────────────────────────────────────────────────────


def outcomes(test, **args):
    """Return each outcome of one run as a status and detail pair."""
    return [(o.status, o.detail) for o in test.run(None, **args)]


def test_the_class_and_generator_forms_are_indistinguishable(rig):
    from_class = outcomes(rig.bench_tests["general"])
    from_generator = outcomes(rig.bench_tests["sweep"])
    assert from_class == from_generator


def test_a_class_lets_its_steps_share_state(rig):
    assert outcomes(rig.bench_tests["ramp"])[2] == (
        StepStatus.PASSED,
        "emitted 4000, running 0",
    )


def test_a_test_that_raises_settles_as_failed_with_no_step_outcomes(rig):
    settled = outcomes(rig.bench_tests["otp"])
    assert len(settled) == 1
    status, detail = settled[0]
    assert status is StepStatus.FAILED
    assert detail.startswith("PermissionError:")
    assert "access policy" in detail


def test_a_run_yields_as_it_goes_rather_than_all_at_once(rig):
    running = rig.bench_tests["general"].run(None)
    assert next(running).detail == "protocol 1"
    assert next(running).detail == "idle, ready"


def test_a_title_is_a_label_and_not_a_sentence(rig):
    assert rig.bench_tests["general"].title == "General check"
    assert rig.bench_tests["general"].description.startswith("Reads the version")
    assert rig.actions["raw.read"].effect == "Read one register."


def test_a_link_test_and_a_bench_test_differ_only_in_needing_the_link(rig):
    link_test = rig.bench_tests["identify_board"]
    bench = rig.bench_tests["general"]

    assert link_test.needs_link is False
    assert bench.needs_link is True
    assert rig.link_tests == (link_test,)
    assert outcomes(link_test) and outcomes(bench)


# ── The form a routine carries ───────────────────────────────────────────────


def test_a_bench_test_carries_the_form_it_declared(rig):
    assert [p["name"] for p in rig.bench_tests["reflash"].params] == ["image"]
    assert current_options(rig.bench_tests["reflash"].params[0]) == ("auto", "v1", "v2")
    assert rig.bench_tests["general"].params == ()


def test_the_form_reaches_the_class_through_its_constructor(rig):
    assert outcomes(rig.bench_tests["reflash"], image="v1") == [
        (StepStatus.PASSED, "chose v1"),
        (StepStatus.PASSED, "wrote v1"),
    ]


def test_the_form_reaches_the_generator_through_its_call(rig):
    assert outcomes(rig.bench_tests["probe"], slot="b")[0] == (
        StepStatus.PASSED,
        "slot b",
    )


def test_a_routine_whose_receiver_does_not_take_a_declared_param_is_refused(declaring):
    with pytest.raises(DeclarationError) as raised:
        declaring(
            "@bench_api.bench_test(params=(bench_api.choice('image', ('v1',)),))\n"
            "class Writer:\n"
            "    @bench_api.step\n"
            "    def only(self, bench): ...\n"
        )
    assert "does not take image" in str(raised.value)


# ── Ending a run early ───────────────────────────────────────────────────────


def test_abandoning_settles_the_step_and_skips_the_rest(rig):
    assert outcomes(rig.bench_tests["reflash"], image="auto") == [
        (StepStatus.PASSED, "already running v2"),
        (StepStatus.SKIPPED, ""),
    ]


def test_abandoning_a_generator_settles_without_failing(rig):
    assert outcomes(rig.bench_tests["probe"], slot="a") == [
        (StepStatus.PASSED, "slot a"),
        (StepStatus.PASSED, "nothing further to read"),
    ]


# ── load() ───────────────────────────────────────────────────────────────────


def test_load_finds_a_bench_test_in_a_module_nothing_imports_by_name(rig):
    # routines.py is named by no import anywhere; walking the package is what
    # makes its decorators run, and forgetting to walk is silent.
    assert "ramp" in rig.bench_tests
    assert rig.bench_tests["ramp"].target.__module__.endswith("fixture.routines")


def test_lookups_reach_a_declaration_by_its_qualified_name(loaded):
    assert loaded.bench_test("rig.ramp").id == "ramp"
    assert loaded.action("rig.raw.move").name == "raw.move"


# ── The import-time errors ───────────────────────────────────────────────────


def test_a_declaration_in_a_package_with_no_subsystem_is_refused():
    body = """
from shared import bench_api

@bench_api.bench_test
class Orphan:
    "Orphan."
    @bench_api.step
    def one(self, bench): ...
"""
    namespace = {"__name__": "nowhere.at.all"}
    with pytest.raises(DeclarationError) as caught:
        exec(compile(body, "nowhere", "exec"), namespace)
    assert "no @subsystem" in str(caught.value)


def test_a_duplicate_subsystem_id_is_refused(declaring):
    with pytest.raises(DeclarationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.subsystem("rig", "A second board answering to the same name.")
class Twin: ...
"""
        )
    assert "two subsystems" in str(caught.value)


def test_a_duplicate_bench_test_id_is_refused(declaring):
    with pytest.raises(DeclarationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.bench_test
class Ramp:
    "Ramp again."
    @bench_api.step
    def one(self, bench): ...
"""
        )
    assert "two bench tests" in str(caught.value)


def test_a_duplicate_action_id_is_refused(declaring):
    with pytest.raises(DeclarationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.action("raw.move")
def move_again(): ...
"""
        )
    assert "two actions" in str(caught.value)


def test_a_bench_test_class_with_no_step_is_refused(declaring):
    with pytest.raises(DeclarationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.bench_test
class Empty:
    "Nothing to do."
"""
        )
    assert "no @step" in str(caught.value)


def test_a_link_test_class_with_no_step_is_refused_the_same_way(declaring):
    with pytest.raises(DeclarationError):
        declaring(
            """
from shared import bench_api

@bench_api.link_test
class AlsoEmpty:
    "Nothing to do either."
"""
        )


def test_a_link_param_naming_something_connect_does_not_take_is_refused(declaring):
    with pytest.raises(DeclarationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.link(params=(bench_api.choice("device", ("a", "b")),))
class Mistyped:
    def can_connect(self, port): ...
    def connect(self, port): ...
    def can_disconnect(self): ...
    def disconnect(self): ...
"""
        )
    assert "does not take device" in str(caught.value)


def test_a_link_missing_one_of_its_four_methods_is_refused(declaring):
    with pytest.raises(DeclarationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.link()
class Halfway:
    def can_connect(self): ...
    def connect(self): ...
"""
        )
    assert "can_disconnect" in str(caught.value)


def test_an_action_whose_params_name_no_such_field_is_refused(declaring):
    with pytest.raises(bench_api.DerivationError) as caught:
        declaring(
            """
from shared import bench_api
from shared.bench_api.tests.fixture.payloads import MoveArgs

@bench_api.action("raw.nudge", params=(bench_api.integer("rpm"),))
def nudge(args: MoveArgs): ...
"""
        )
    assert "rpm" in str(caught.value)


def test_an_action_declaring_params_over_nothing_derived_is_refused(declaring):
    with pytest.raises(bench_api.DerivationError) as caught:
        declaring(
            """
from shared import bench_api

@bench_api.action("raw.nudge", params=(bench_api.integer("rpm"),))
def nudge(): ...
"""
        )
    assert "rpm" in str(caught.value)


def test_an_action_splits_its_prose_into_the_line_and_the_rest(rig):
    read = rig.actions["raw.read"]
    assert read.effect == "Read one register."
    assert read.description == "Answers from the cache when the slot is still valid."

    version = rig.actions["sys.version"]
    assert version.effect == "Report the protocol version."


def test_an_action_over_a_field_no_kind_renders_is_refused(declaring):
    with pytest.raises(bench_api.DerivationError) as caught:
        declaring(
            """
from shared import bench_api
from shared.bench_api.tests.fixture.payloads import Unrenderable

@bench_api.action("raw.impossible")
def impossible(args: Unrenderable): ...
"""
        )
    assert "Unrenderable.when" in str(caught.value)


# ── The parameter dictionaries ───────────────────────────────────────────────


def test_a_param_of_a_kind_no_control_renders_is_refused(declaring):
    with pytest.raises(bench_api.ParamError) as caught:
        declaring(
            "@bench_api.bench_test(params=({'name': 'image', 'kind': 'integr'},))\n"
            "class Misspelt:\n"
            "    @bench_api.step\n"
            "    def only(self, bench): ...\n"
        )
    assert "'integr'" in str(caught.value)


def test_a_param_carrying_a_key_its_kind_has_no_use_for_is_refused(declaring):
    with pytest.raises(bench_api.ParamError) as caught:
        declaring(
            "@bench_api.bench_test(params=("
            "{'name': 'image', 'kind': 'integer', 'maximum': 3},))\n"
            "class Astray:\n"
            "    @bench_api.step\n"
            "    def only(self, bench): ...\n"
        )
    assert "carries no maximum" in str(caught.value)


def test_a_choice_declaring_no_options_is_refused(declaring):
    with pytest.raises(bench_api.ParamError) as caught:
        declaring(
            "@bench_api.bench_test(params=({'name': 'image', 'kind': 'choice'},))\n"
            "class Empty:\n"
            "    @bench_api.step\n"
            "    def only(self, bench): ...\n"
        )
    assert "needs options" in str(caught.value)


def test_a_column_of_a_group_is_refused_on_the_same_terms(declaring):
    with pytest.raises(bench_api.ParamError) as caught:
        declaring(
            "@bench_api.bench_test(params=(bench_api.group('ops', columns=("
            "{'name': 'reg', 'kind': 'integr'},)),))\n"
            "class Nested:\n"
            "    @bench_api.step\n"
            "    def only(self, bench): ...\n"
        )
    assert "'integr'" in str(caught.value)


# ── Making the call ──────────────────────────────────────────────────────────


def test_an_action_is_called_with_the_argument_object_its_annotation_names(rig):
    read = rig.actions["raw.read"]
    assert read.argument_type is not None
    seen = []
    object.__setattr__(read, "target", seen.append)
    read.call({"idx": 2, "reg": 3, "nothing_declares_this": 9})
    assert dataclasses.asdict(seen[0]) == {"idx": 2, "reg": 3}


def test_an_action_annotating_nothing_is_called_bare(rig):
    version = rig.actions["sys.version"]
    assert version.argument_type is None
    seen = []
    object.__setattr__(version, "target", lambda: seen.append("called"))
    version.call({"ignored": 1})
    assert seen == ["called"]
