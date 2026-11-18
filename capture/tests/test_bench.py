"""What the bench offers, what it refuses, and what running one leaves behind."""

import pytest

import capture
from capture.tests import fake
from shared.diagnostics import FAILED, PASSED
from shared.subsystem import READY, LinkState, NotReady


@pytest.fixture
def loaded():
    """Return the subsystem, with nothing connected."""
    return capture.SUBSYSTEM(capture)


@pytest.fixture
def linked(monkeypatch):
    """Connect to a camera that is not there, and disconnect however the test ends."""
    sub = capture.SUBSYSTEM(capture, fake.Transport())
    monkeypatch.setattr(sub, "probe", lambda target: READY)
    sub.connect("10.0.0.2")
    yield sub
    sub.disconnect()


@pytest.fixture
def connected(linked):
    """Return the fake camera on the far end of the link."""
    return linked._transport.camera


def outcomes(subsystem, key, values=None):
    """Run one test and hand back everything it said."""
    return list(subsystem.run_test(key, values or {}, lambda said: None).outcomes)


# ── What is declared ─────────────────────────────────────────────────────────


def test_every_stage_of_the_camera_s_life_has_a_group(loaded):
    groups = {item.group for item in loaded.tests}

    assert {"discover", "basics", "shots", "filesystem", "events"} <= groups


def test_a_setting_is_read_and_written_by_commands_nobody_wrote_out(loaded):
    made = [one.key for one in loaded.commands if one.group == "calls"]

    assert len(made) > 150
    assert "calls.read_iso" in made
    assert "calls.write_iso" in made


# ── What may run, and when ───────────────────────────────────────────────────


def test_nothing_that_needs_a_camera_may_run_before_there_is_one(loaded):
    assert loaded.link_state() is LinkState.DOWN

    assert not loaded.readiness("shots.Captures")


def test_the_ladder_runs_only_while_nothing_holds_the_camera(linked):
    verdict = linked.readiness("discover.Search")

    assert not verdict
    assert "disconnect" in str(verdict)


def test_connecting_twice_is_refused_rather_than_done(linked):
    with pytest.raises(NotReady):
        linked.connect("10.0.0.2")


# ── What running one does ────────────────────────────────────────────────────


def test_connecting_reports_the_versions_it_accepted(linked):
    assert linked.link_state() is LinkState.UP
    found = linked.camera()
    assert found.link.registry.versions == ("ver100", "ver110", "ver140")
    assert found.link.manifest
    assert linked.facts() is not None


def test_a_frame_is_taken_each_way_confirmed_and_swept_up_after(linked, connected):
    said = outcomes(linked, "shots.Captures")

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.shots == 2
    assert connected.files == []


def test_the_manual_way_presses_lets_go_and_takes_the_same_photograph(
    linked, connected
):
    outcomes(linked, "shots.Captures")

    actions = [
        payload["action"]
        for _, path, payload in connected.sent
        if path.endswith("manual") and payload
    ]
    assert actions == ["half_press", "full_press", "release"]


def test_neither_release_drives_the_lens(linked, connected):
    outcomes(linked, "shots.Captures")

    asked = [
        payload["af"]
        for _, path, payload in connected.sent
        if "shutterbutton" in path and payload and "af" in payload
    ]
    assert asked and not any(asked)


def test_a_frame_rate_run_stops_on_the_clock_and_reports_what_it_achieved(
    linked, connected
):
    said = outcomes(linked, "shots.FrameRate", {"seconds": 1, "busy wait": 0})

    measured = next(one for one in said if one.step == "Measure")
    assert connected.shots > 0
    assert measured.result is not None
    fields = dict(measured.result.fields)
    assert fields["achieved"].endswith("frames/s")
    assert fields["thermal before"] == "NORMAL"
    assert fields["landed"] == str(connected.shots)


def test_a_frame_rate_run_owns_its_own_wait_and_puts_the_policy_back(linked, connected):
    link = linked.camera().link
    was = (link.retries, link.backoff)

    outcomes(linked, "shots.FrameRate", {"seconds": 1, "busy wait": 0})

    assert (link.retries, link.backoff) == was


def test_a_written_setting_is_read_back_and_left_as_written(linked, connected):
    reply = linked.run_command("calls.write_iso", {"value": "800"})

    assert reply.summary == "asked '800', got '800'"
    assert connected.settings["shooting/settings/iso"] == "800"


def test_a_setting_this_camera_lacks_says_so_rather_than_vanishing(linked):
    verdict = linked.readiness("calls.read_wbshift")

    assert not verdict
    assert "does not offer" in str(verdict)


def test_a_setting_is_moved_one_notch_and_put_back(linked, connected):
    said = outcomes(linked, "basics.ReadAndWrite")

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.settings["shooting/settings/iso"] == "400"


def test_moving_a_setting_asks_for_a_neighbour_of_what_was_there(linked, connected):
    outcomes(linked, "basics.ReadAndWrite")

    asked = [
        payload["value"]
        for _, path, payload in connected.sent
        if path.endswith("settings/iso") and payload
    ]
    assert asked == ["800", "400"]


def test_health_reads_the_body_without_touching_it(linked, connected):
    said = outcomes(linked, "basics.Health")

    assert [one.status for one in said] == [PASSED, PASSED]
    assert connected.shots == 0


def test_the_card_is_walked_written_read_and_left_as_it_was(linked, connected):
    before = list(connected.files)

    said = outcomes(linked, "filesystem.Files")

    assert [one.status for one in said] == [PASSED] * 6
    assert connected.files == before


def test_the_download_carries_a_picture_the_screen_can_show(linked, connected):
    said = outcomes(linked, "filesystem.Files")

    pulled = next(one for one in said if one.step == "Download it")
    assert pulled.result is not None
    assert pulled.result.image is not None
    assert pulled.result.image.startswith(fake.JPEG)


def test_a_frame_is_found_by_walking_as_well_as_by_the_event(linked, connected):
    said = outcomes(linked, "filesystem.Files")

    walked = next(one for one in said if one.step == "Find it without the event")
    assert walked.status is PASSED
    assert walked.result is not None
    assert dict(walked.result.fields)["count grew by"] == "1"


def test_a_survey_leaves_nothing_behind_unless_asked(linked, connected):
    said = outcomes(linked, "survey.Everything", {"keep": False})

    assert said[0].status is PASSED
    assert "Canon EOS R50" in said[0].detail


def test_nothing_landing_fails_the_run_rather_than_hanging(
    linked, connected, monkeypatch
):
    monkeypatch.setattr("capture.bench.shots.SETTLE", 0.0)
    monkeypatch.setattr(fake.Camera, "shoot", lambda self: {})

    said = outcomes(linked, "shots.Captures")

    assert any(one.status is FAILED for one in said)
