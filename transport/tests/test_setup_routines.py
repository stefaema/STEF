"""What a bring-up puts on the wire, and how each of its steps settles."""

import pytest

from shared import bench_api, fw_api
from shared.bench_api import FAILED, PASSED, SKIPPED, WARNED
from transport import device_profile, transport
from transport.bench import setup

BASELINE = "capstan_base"


class Raw:
    """The `raw` namespace, answering without a board and remembering what it was sent."""

    def __init__(self, agrees=True, mismatched=0, conditions=0):
        self.sent = []
        self.agrees = agrees
        self.mismatched = mismatched
        self.conditions = conditions

    def _record(self, name, **values):
        spec = fw_api.namespaces()["raw"][name]
        self.sent.append((name, fw_api.arguments(spec, (), values)))

    def bringup(self, **values):
        self._record("bringup", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_bringup_ret)(gstat_at_bringup=1)

    def verify_config(self, **values):
        self._record("verify_config", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_verify_config_ret)(
            mismatched=self.mismatched, agrees=self.agrees
        )

    def poll_health(self, **values):
        self._record("poll_health", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_poll_health_ret)(
            conditions=self.conditions
        )

    def read(self, **values):
        self._record("read", **values)
        return fw_api.dataclass_for(fw_api.rpc_raw_read_ret)(value=0x1234)


@pytest.fixture
def raw(monkeypatch):
    """Answer every call this routine makes, with the link reporting itself up."""
    answering = Raw()
    monkeypatch.setattr(
        transport, "firmware", lambda: type("Link", (), {"raw": answering})()
    )
    return answering


def outcomes(declared, raw, **values):
    """Return every outcome the bring-up yields, in order."""
    return list(
        bench_api.run_routine(declared.routines["setup.baseline_bringup"], values)
    )


def payload_of(raw, name):
    """Return what one call put on the wire."""
    return next(sent for called, sent in raw.sent if called == name)


# ── The run ──────────────────────────────────────────────────────────────────


def test_every_step_settles_and_the_driver_ends_configured(declared, raw):
    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert [step.status for step in settled[:4]] == [PASSED] * 4
    assert [step.step for step in settled[:4]] == [
        setup.PROFILE,
        setup.BRING_UP,
        setup.READ_BACK,
        setup.HEALTH,
    ]


def test_the_registers_read_back_after_the_named_steps_number_themselves(declared, raw):
    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert [step.step for step in settled[4:]] == ["#5", "#6"]


def test_the_bringup_carries_the_profile_as_the_firmware_frames_it(declared, raw):
    outcomes(declared, raw, idx=1, profile=BASELINE)

    args = fw_api.unpack(fw_api.rpc_raw_write_args, payload_of(raw, "bringup"))
    assert args.idx == 1

    written = {device_profile.register_name(op.reg): op.value for op in args.ops}
    assert written["CHOPCONF"] == device_profile.value_of(
        "chopconf", device_profile.load(BASELINE)["chopconf"]
    )


def test_a_profile_that_does_not_load_stops_the_run_before_the_wire(declared, raw):
    settled = outcomes(declared, raw, idx=0, profile="nothing_installed")

    assert settled[0].status is FAILED
    assert [step.status for step in settled[1:]] == [SKIPPED] * 3
    assert raw.sent == []


def test_a_driver_holding_something_else_fails_the_read_back(
    declared, raw, monkeypatch
):
    raw.agrees = False
    raw.mismatched = 1 << fw_api.tmc2209_reg_slot(fw_api.TMC2209_GCONF)

    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert settled[2].status is FAILED
    assert "GCONF" in settled[2].detail
    assert settled[3].status is SKIPPED


def test_a_condition_is_reported_and_never_fails_the_run(declared, raw):
    raw.conditions = int(fw_api.TMC2209_OVERTEMP_WARNING)

    settled = outcomes(declared, raw, idx=0, profile=BASELINE)

    assert settled[3].status is WARNED
    assert "OVERTEMP_WARNING" in settled[3].detail
    assert len(settled) > 4
