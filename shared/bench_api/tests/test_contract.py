"""Readiness, state and the results vocabulary."""

import dataclasses

import pytest

from shared import bench_api
from shared.bench_api import READY, Level, Status, blocked, worst

# ── Readiness ────────────────────────────────────────────────────────────────


def test_a_ready_verdict_is_truthy_and_says_nothing():
    assert READY
    assert str(READY) == ""
    assert READY.reason is None


def test_a_blocked_verdict_is_falsy_and_carries_its_reason():
    refused = blocked("no board on that port")
    assert not refused
    assert str(refused) == "no board on that port"


def test_a_probe_that_falls_off_the_end_leaves_the_control_disabled():
    def can_connect(_port):
        """Return nothing at all, which is what a forgotten branch does."""

    assert not can_connect("auto")


def test_a_verdict_cannot_be_edited_after_the_fact():
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(READY, "reason", "changed my mind")


def test_two_refusals_for_the_same_reason_are_the_same_verdict():
    assert blocked("not connected") == blocked("not connected")
    assert blocked("not connected") != READY


# ── State ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("left", list(Status))
@pytest.mark.parametrize("right", list(Status))
def test_worst_of_a_pair_is_the_one_that_ranks_higher(left, right):
    got = worst([left, right])
    assert got in (left, right)
    assert bench_api.SEVERITY.index(got) == max(
        bench_api.SEVERITY.index(left), bench_api.SEVERITY.index(right)
    )


def test_worst_is_the_order_the_screen_reports():
    assert worst([Status.PASSED, Status.WARNED]) is Status.WARNED
    assert worst([Status.WARNED, Status.FAILED]) is Status.FAILED
    assert worst([Status.SKIPPED, Status.PASSED]) is Status.PASSED


def test_a_run_of_nothing_but_skips_is_not_reported_as_a_pass():
    assert worst([Status.SKIPPED, Status.SKIPPED]) is Status.SKIPPED
    assert worst([]) is Status.SKIPPED


def test_a_subsystem_state_is_not_the_firmwares_mode():
    assert {s.value for s in bench_api.SubsystemState} == {
        "down",
        "linking",
        "up",
        "error",
    }


def test_a_result_carries_one_vocabulary_whoever_produced_it():
    found = bench_api.Result(level=Level.OK, summary="0x000000c1", note="from cache")
    assert found.level is Level.OK
    assert found.raw is None
    assert found.table is None
