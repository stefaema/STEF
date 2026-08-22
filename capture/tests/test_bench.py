"""What the bench offers, what it refuses, and what running one leaves behind."""

from __future__ import annotations

import pytest

from capture import capture
from capture.tests import fake
from shared import bench_api
from shared.bench_api import FAILED, PASSED, WARNED, SubsystemState
from shared.subsystem import SubsystemSpec


@pytest.fixture(scope="session")
def loaded():
    """Load the subsystem once.

    Once and not per test: a declaration runs when its module is imported, and
    the second import of anything is a no-op, so clearing the registry between
    tests would leave every later one with nothing declared.
    """
    bench_api.REGISTRY.clear()
    return bench_api.derive(SubsystemSpec.of_package("capture"))


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

    assert {"discover", "link", "setup", "shots", "filesystem", "events"} <= groups


def test_a_setting_is_read_and_written_by_routines_nobody_wrote_out(loaded):
    made = [name for name in loaded.routines if name.startswith("calls.")]

    assert len(made) > 150
    assert "calls.read_iso" in loaded.routines
    assert "calls.write_iso" in loaded.routines


# ── What may run, and when ───────────────────────────────────────────────────


def test_nothing_that_needs_a_camera_may_run_before_there_is_one(loaded):
    assert capture.state() is SubsystemState.DOWN
    item = bench_api.REGISTRY.routine("capture", "shots.one_frame")

    assert not bench_api.readiness_of(item, capture.state())


def test_the_ladder_runs_only_while_nothing_holds_the_camera(loaded, connected):
    item = bench_api.REGISTRY.routine("capture", "discover.search")

    verdict = bench_api.readiness_of(item, capture.state())

    assert not verdict
    assert "disconnect" in str(verdict)


def test_connecting_twice_is_refused_rather_than_done(loaded, connected):
    item = bench_api.REGISTRY.routine("capture", "link.connect")

    assert not bench_api.readiness_of(item, capture.state())


# ── What running one does ────────────────────────────────────────────────────


def test_connecting_reports_the_versions_it_accepted(loaded):
    transport = fake.Transport()
    capture.open_link("10.0.0.2", transport)
    try:
        assert capture.state() is SubsystemState.UP
        found = capture.camera()
        assert found.link.registry.versions == ("ver100", "ver110", "ver140")
        assert found.link.manifest
    finally:
        capture.close_link()


def test_a_frame_is_taken_confirmed_and_swept_up_after(loaded, connected):
    said = outcomes(loaded, "shots.one_frame")

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.shots == 1
    assert connected.files == []


def test_the_manual_way_takes_the_same_photograph(loaded, connected):
    said = outcomes(loaded, "shots.one_frame_by_hand")

    actions = [
        payload["action"]
        for _, path, payload in connected.sent
        if path.endswith("manual") and payload
    ]
    assert actions == ["half_press", "full_press", "release"]
    assert all(one.status is PASSED for one in said)


def test_half_pressing_and_letting_go_takes_no_photograph(loaded, connected):
    said = outcomes(loaded, "shots.half_press_takes_nothing")

    assert said[-1].status is PASSED
    assert connected.shots == 0


def test_a_burst_reports_what_it_achieved_rather_than_what_was_asked(loaded, connected):
    said = outcomes(loaded, "shots.burst", {"frames": 4, "interval": 0})

    measured = next(one for one in said if one.step == "Measure")
    assert connected.shots == 4
    assert measured.value is not None
    fields = dict(measured.value.fields)
    assert fields["achieved"].endswith("frames/s")
    assert fields["thermal before"] == "NORMAL"


def test_a_written_setting_is_checked_and_put_back(loaded, connected):
    said = outcomes(loaded, "calls.write_iso", {"value": "800"})

    assert [one.status for one in said] == [PASSED, PASSED, PASSED]
    assert connected.settings["shooting/settings/iso"] == "400"


def test_a_setting_this_camera_lacks_says_so_rather_than_vanishing(loaded, connected):
    item = bench_api.REGISTRY.routine("capture", "calls.read_wbshift")

    verdict = bench_api.readiness_of(item, capture.state())

    assert not verdict
    assert "does not offer" in str(verdict)


def test_the_recipe_reports_what_did_not_take(loaded, connected):
    said = outcomes(loaded, "setup.prepare_for_scanning")

    assert said[-1].status in (PASSED, WARNED)
    assert connected.settings["shooting/settings/drive"] == "single"


def test_a_survey_leaves_nothing_behind_unless_asked(loaded, connected):
    said = outcomes(loaded, "survey.everything", {"keep": False})

    assert said[0].status is PASSED
    assert "Canon EOS R50" in said[0].detail


def test_nothing_landing_fails_the_run_rather_than_hanging(
    loaded, connected, monkeypatch
):
    monkeypatch.setattr("capture.bench.shots.SETTLE", 0.0)
    monkeypatch.setattr(fake.Camera, "shoot", lambda self: {})

    said = outcomes(loaded, "shots.one_frame")

    assert any(one.status is FAILED for one in said)
