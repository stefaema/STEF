from shared.diagnostics import LINK_KEY, PASSED, as_json
from shared.subsystem import LinkState


def test_a_subsystem_view_carries_its_identity_link_and_declarations(oven):
    seen = oven.view()

    assert (seen.id, seen.summary, seen.safe_state) == (
        "fixture",
        "The oven.",
        "element off",
    )
    assert seen.link is not None
    assert seen.link.state is LinkState.UP
    assert [one.key for one in seen.tests][:2] == ["heat.Preheat", "heat.Breaks"]
    assert [one.key for one in seen.commands] == ["calls.set_element", "calls.broken"]


def test_a_test_view_previews_its_steps_and_its_end(oven):
    preheat = oven.view().tests[0]

    assert [one.title for one in preheat.steps] == [
        "Write setpoint",
        "Wait for the probe",
    ]
    assert preheat.steps[0].hazard == "switches the element on"
    assert preheat.end is not None and preheat.end.title == "Element off"
    assert preheat.hazardous
    assert preheat.last is None


def test_a_finished_run_is_the_test_s_last_result(oven):
    oven.run_test("heat.Preheat", {"celsius": "180"}, lambda said: None)

    last = oven.view().tests[0].last

    assert last is not None
    assert last.verdict is PASSED
    assert not last.running
    assert last.values == {"celsius": 180}


def test_options_that_move_carry_the_address_to_ask_again(oven):
    target = oven.view().link.target

    assert target.options is None
    assert target.reload == ("fixture", LINK_KEY, "port")
    assert oven.options(LINK_KEY, "port") == (
        {"value": "/dev/oven0", "label": "/dev/oven0"},
    )


def test_a_readiness_is_shown_with_its_reason(oven):
    guarded = next(one for one in oven.view().tests if one.key == "heat.Guarded")

    assert guarded.readiness.reason == "the element is hot"


def test_a_view_turns_into_json(oven):
    oven.run_test("heat.Preheat", {"celsius": "180"}, lambda said: None)

    packed = as_json(oven.view())

    assert packed["link"]["state"] == "up"
    preheat = packed["tests"][0]
    assert preheat["needs"] == "up"
    assert preheat["readiness"] == {"ok": True, "reason": None}
    assert preheat["last"]["outcomes"][0]["status"] == "passed"
