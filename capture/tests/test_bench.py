"""What the bench offers, what it refuses, and what running one leaves behind."""

from __future__ import annotations

import importlib

import pytest

from capture import capture
from capture.tests import fake
from shared import bench_api
from shared.bench_api import FAILED, PASSED, SubsystemLinkState
from shared.subsystem import SubsystemSpec


@pytest.fixture(scope="session")
def loaded():
    """Load the subsystem once.

    Once and not per test: a declaration runs when its module is imported, and
    the second import of anything is a no-op, so clearing the registry between
    tests would leave every later one with nothing declared.
    """
    bench_api.REGISTRY.clear()
    return bench_api.derive(SubsystemSpec.of(importlib.import_module("capture")))


@pytest.fixture
def connected(loaded):
    """Connect to a camera that is not there, and disconnect however the test ends."""
    transport = fake.Transport()
    capture.open_link("10.0.0.2", transport)
    yield transport.camera
    capture.close_link()


def outcomes(subsystem, key, values=None):
    """Run one routine and hand back everything it said."""
    item = bench_api.REGISTRY.routine(subsystem.id, key)
    return list(bench_api.run_routine(item, values or {}))


# ── What is declared ─────────────────────────────────────────────────────────


def test_every_stage_of_the_camera_s_life_has_a_group(loaded):
    groups = {item.group for item in loaded.routines.values()}

    assert {"discover", "link", "basics", "shots", "filesystem", "events"} <= groups


def test_a_setting_is_read_and_written_by_routines_nobody_wrote_out(loaded):
    made = [name for name in loaded.routines if name.startswith("calls.")]

    assert len(made) > 150
    assert "calls.read_iso" in loaded.routines
    assert "calls.write_iso" in loaded.routines


# ── What may run, and when ───────────────────────────────────────────────────


def test_nothing_that_needs_a_camera_may_run_before_there_is_one(loaded):
    assert capture.link_state() is SubsystemLinkState.DOWN
    item = bench_api.REGISTRY.routine("capture", "shots.captures")

    assert not bench_api.readiness_of(item, capture.link_state())


def test_the_ladder_runs_only_while_nothing_holds_the_camera(loaded, connected):
    item = bench_api.REGISTRY.routine("capture", "discover.search")

    verdict = bench_api.readiness_of(item, capture.link_state())

    assert not verdict
    assert "disconnect" in str(verdict)


def test_connecting_twice_is_refused_rather_than_done(loaded, connected):
    item = bench_api.REGISTRY.routine("capture", "link.connect")

    assert not bench_api.readiness_of(item, capture.link_state())


# ── What running one does ────────────────────────────────────────────────────


def test_connecting_reports_the_versions_it_accepted(loaded):
    transport = fake.Transport()
    capture.open_link("10.0.0.2", transport)
    try:
        assert capture.link_state() is SubsystemLinkState.UP
        found = capture.camera()
        assert found.link.registry.versions == ("ver100", "ver110", "ver140")
        assert found.link.manifest
    finally:
        capture.close_link()


def test_a_frame_is_taken_each_way_confirmed_and_swept_up_after(loaded, connected):
    said = outcomes(loaded, "shots.captures")

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.shots == 2
    assert connected.files == []


def test_the_manual_way_presses_lets_go_and_takes_the_same_photograph(
    loaded, connected
):
    outcomes(loaded, "shots.captures")

    actions = [
        payload["action"]
        for _, path, payload in connected.sent
        if path.endswith("manual") and payload
    ]
    assert actions == ["half_press", "full_press", "release"]


def test_neither_release_drives_the_lens(loaded, connected):
    outcomes(loaded, "shots.captures")

    asked = [
        payload["af"]
        for _, path, payload in connected.sent
        if "shutterbutton" in path and payload and "af" in payload
    ]
    assert asked and not any(asked)


def test_a_frame_rate_run_stops_on_the_clock_and_reports_what_it_achieved(
    loaded, connected
):
    said = outcomes(loaded, "shots.frame_rate", {"seconds": 1, "busy wait": 0})

    measured = next(one for one in said if one.step == "Measure")
    assert connected.shots > 0
    assert measured.value is not None
    fields = dict(measured.value.fields)
    assert fields["achieved"].endswith("frames/s")
    assert fields["thermal before"] == "NORMAL"
    assert fields["landed"] == str(connected.shots)


def test_a_frame_rate_run_owns_its_own_wait_and_puts_the_policy_back(loaded, connected):
    link = capture.camera().link
    was = (link.retries, link.backoff)

    outcomes(loaded, "shots.frame_rate", {"seconds": 1, "busy wait": 0})

    assert (link.retries, link.backoff) == was


def test_a_written_setting_is_checked_and_put_back(loaded, connected):
    said = outcomes(loaded, "calls.write_iso", {"value": "800"})

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.settings["shooting/settings/iso"] == "400"


def test_a_setting_this_camera_lacks_says_so_rather_than_vanishing(loaded, connected):
    item = bench_api.REGISTRY.routine("capture", "calls.read_wbshift")

    verdict = bench_api.readiness_of(item, capture.link_state())

    assert not verdict
    assert "does not offer" in str(verdict)


def test_a_setting_is_moved_one_notch_and_put_back(loaded, connected):
    said = outcomes(loaded, "basics.read_and_write")

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.settings["shooting/settings/iso"] == "400"


def test_moving_a_setting_asks_for_a_neighbour_of_what_was_there(loaded, connected):
    outcomes(loaded, "basics.read_and_write")

    asked = [
        payload["value"]
        for _, path, payload in connected.sent
        if path.endswith("settings/iso") and payload
    ]
    assert asked == ["800", "400"]


def test_health_reads_the_body_without_touching_it(loaded, connected):
    said = outcomes(loaded, "basics.health")

    assert [one.status for one in said] == [PASSED, PASSED]
    assert connected.shots == 0


def test_the_card_is_walked_written_read_and_left_as_it_was(loaded, connected):
    before = list(connected.files)

    said = outcomes(loaded, "filesystem.files")

    assert [one.status for one in said] == [PASSED] * 6
    assert connected.files == before


def test_the_download_carries_a_picture_the_screen_can_show(loaded, connected):
    said = outcomes(loaded, "filesystem.files")

    pulled = next(one for one in said if one.step == "Download it")
    assert pulled.value is not None
    assert pulled.value.image is not None
    assert pulled.value.image.startswith(fake.JPEG)


def test_a_frame_is_found_by_walking_as_well_as_by_the_event(loaded, connected):
    said = outcomes(loaded, "filesystem.files")

    walked = next(one for one in said if one.step == "Find it without the event")
    assert walked.status is PASSED
    assert walked.value is not None
    assert dict(walked.value.fields)["count grew by"] == "1"


def test_a_survey_leaves_nothing_behind_unless_asked(loaded, connected):
    said = outcomes(loaded, "survey.everything", {"keep": False})

    assert said[0].status is PASSED
    assert "Canon EOS R50" in said[0].detail


def test_nothing_landing_fails_the_run_rather_than_hanging(
    loaded, connected, monkeypatch
):
    monkeypatch.setattr("capture.bench.shots.SETTLE", 0.0)
    monkeypatch.setattr(fake.Camera, "shoot", lambda self: {})

    said = outcomes(loaded, "shots.captures")

    assert any(one.status is FAILED for one in said)
