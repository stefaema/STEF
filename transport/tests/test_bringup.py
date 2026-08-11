import pytest

from shared import bench_api, fw_api
from shared.bench_api import StepStatus
from transport import device_profile


class Raw:
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


class Bench:
    def __init__(self, raw):
        self.firmware = type("Link", (), {"raw": raw})()


@pytest.fixture
def raw():
    return Raw()


def outcomes(raw, **args):
    bench_api.load("transport.bench")
    test = bench_api.REGISTRY.bench_test("transport.bring_up_driver_baseline")
    return list(test.run(Bench(raw), **args)), test


def payload_of(raw, name):
    return next(sent for called, sent in raw.sent if called == name)


# ── The run ──────────────────────────────────────────────────────────────────


def test_every_step_settles_and_the_driver_ends_configured(raw):
    settled, test = outcomes(raw, idx=0, profile="capstan_base")

    assert len(settled) == len(test.steps)
    assert [step.status for step in settled] == [StepStatus.PASSED] * len(test.steps)


def test_the_bringup_carries_all_ten_registers_as_the_firmware_frames_them(raw):
    outcomes(raw, idx=1, profile="capstan_base")

    payload = payload_of(raw, "bringup")
    args = fw_api.unpack(fw_api.rpc_raw_write_args, payload)
    assert args.idx == 1

    written = {device_profile.register_name(op.reg): op.value for op in args.ops}
    assert written["CHOPCONF"] == device_profile.value_of(
        "chopconf", device_profile.load("capstan_base")["chopconf"]
    )


def test_a_profile_that_does_not_load_stops_the_run_before_the_wire(raw):
    settled, test = outcomes(raw, idx=0, profile="nothing_installed")

    assert settled[0].status is StepStatus.FAILED
    assert [step.status for step in settled[1:]] == [StepStatus.SKIPPED] * (
        len(test.steps) - 1
    )
    assert raw.sent == []


def test_a_driver_holding_something_else_fails_the_read_back():
    raw = Raw(
        agrees=False, mismatched=1 << fw_api.tmc2209_reg_slot(fw_api.TMC2209_GCONF)
    )
    settled, _ = outcomes(raw, idx=0, profile="capstan_base")

    verify = settled[2]
    assert verify.status is StepStatus.FAILED
    assert "GCONF" in verify.detail


def test_a_condition_is_reported_and_never_fails_the_run():
    raw = Raw(conditions=int(fw_api.TMC2209_OVERTEMP_WARNING))
    settled, _ = outcomes(raw, idx=0, profile="capstan_base")

    health = settled[3]
    assert health.status is StepStatus.WARNED
    assert "OVERTEMP_WARNING" in health.detail
