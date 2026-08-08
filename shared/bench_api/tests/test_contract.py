"""Readiness, state and the results vocabulary."""

import dataclasses

import pytest

from shared import bench_api
from shared.bench_api import READY, Level, blocked

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
