import pytest

from shared.diagnostics import Diagnosable, Test, end, step
from shared.diagnostics.tests.fixture import calls, heat
from shared.subsystem import DeclarationError, Input


def test_a_test_takes_its_key_and_prose_from_where_it_is_written():
    assert heat.Preheat.key == "heat.Preheat"
    assert heat.Preheat.title == "Preheat the oven"
    assert heat.Preheat.description.startswith("Writes one setpoint")


def test_a_test_with_no_docstring_of_its_own_does_not_borrow_its_base_s():
    class Plain(heat.Holds):
        pass

    assert Plain.title == "Plain"


def test_the_preview_is_the_collected_steps_and_the_end():
    assert [one.title for one in heat.Preheat.steps] == [
        "Write setpoint",
        "Wait for the probe",
    ]
    assert heat.Preheat.end_step is not None
    assert heat.Preheat.end_step.title == "Element off"


def test_a_test_is_hazardous_when_one_of_its_steps_is():
    assert heat.Preheat.hazardous()
    assert not heat.Breaks.hazardous()


def test_questions_are_the_inputs_declared_beside_the_form():
    assert [one.name for one in heat.Asks.questions] == ["smelled", "continue"]
    assert heat.Preheat.questions == ()


def test_a_subclass_replaces_a_base_step_in_place():
    class Gentle(heat.ElementReady):
        @step("Element on gently", hazard="switches the element on")
        def element_on(self) -> None:
            pass

    assert [one.title for one in Gentle.steps] == ["Identify", "Element on gently"]


def test_two_steps_with_one_title_are_refused():
    with pytest.raises(DeclarationError, match="two steps titled 'Heat'"):

        class Twice(Test[object]):
            @step("Heat")
            def first(self) -> None:
                pass

            @step("Heat")
            def second(self) -> None:
                pass


def test_a_second_end_step_is_refused():
    with pytest.raises(DeclarationError, match="second end step"):

        class Ends(Test[object]):
            @end("Off")
            def off(self) -> None:
                pass

            @end("Really off")
            def really_off(self) -> None:
                pass


def test_an_input_no_control_renders_is_refused():
    with pytest.raises(DeclarationError, match="which no control renders"):

        class Dial(Test[object]):
            inputs = (Input(name="celsius", kind="dial"),)


def test_one_key_declared_twice_in_a_subsystem_is_refused():
    with pytest.raises(DeclarationError, match="heat.Preheat more than once"):

        class Twice(Diagnosable):
            tests = (heat.Preheat, heat.Preheat)


def test_a_command_takes_its_key_and_prose_from_its_function():
    assert calls.set_element.key == "calls.set_element"
    assert calls.set_element.title == "Switch the element"
    assert calls.set_element.description == "Writes the setpoint and leaves it there."
