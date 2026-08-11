from __future__ import annotations

from typing import Any

from shared import bench_api, fw_api
from shared.bench_api import Level, Result, StepOutcome, StepStatus, Table
from transport import device_profile
from transport.bench.actions import devices

READ_BACK = (fw_api.TMC2209_GCONF, fw_api.TMC2209_CHOPCONF)


def _hex(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08x}"


def _flags(decoded: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        (field, "true" if isinstance(value, bool) and value else str(int(value)))
        for field, *_ in type(decoded)._fields_
        if not field.startswith("_")
        for value in (getattr(decoded, field),)
    )


def _asked(ops: tuple[Any, ...]) -> Table:
    return Table(
        head=("register", "value"),
        rows=tuple(
            (device_profile.register_name(op.reg), _hex(op.value)) for op in ops
        ),
    )


@bench_api.bench_test(
    hazardous=True,
    params=(
        bench_api.choice(
            "idx",
            devices,
            hint="Which driver to claim, by the name the board declares for it.",
        ),
        bench_api.choice(
            "profile",
            device_profile.names,
            hint="Which profile to write, out of the ones installed here.",
        ),
    ),
)
class BringUpDriverBaseline:
    """Bring a driver up to its baseline.

    Writes one configuration profile onto a driver and asks what it made of it.
    Ends with the driver holding every owned register, standing still, and its
    power stage untouched.

    A baseline is tuned for no load in particular. It is what proves the driver,
    the wiring and the link work, and it is where a profile for a real load
    starts. The file names the fields the datasheet names, so what reaches the
    wire is the firmware's own encoding of it.
    """

    def __init__(self, idx: int = 0, profile: str = "capstan_base") -> None:
        self.idx = int(idx)
        self.name = profile
        self.ops: tuple[Any, ...] = ()

    @bench_api.step
    def profile(self, bench: Any) -> StepOutcome:
        """Profile."""
        try:
            written = device_profile.load(self.name)
            self.ops = device_profile.ops(written)
        except Exception as exc:
            raise bench_api.Abandoned(
                f"{self.name} is not a configuration this driver can be given: {exc}",
                StepStatus.FAILED,
            ) from exc

        return StepOutcome(
            StepStatus.PASSED,
            f"{self.name} covers all {len(self.ops)} owned registers",
            Result(
                level=Level.OK,
                summary=f"{self.name}, as the firmware's own codecs encode it",
                fields=(("profile", self.name),),
                table=_asked(self.ops),
            ),
        )

    @bench_api.step
    def bringup(self, bench: Any) -> StepOutcome:
        """Bring-up."""
        reply = bench.firmware.raw.bringup(idx=self.idx, ops=list(self.ops))
        found = reply.gstat_at_bringup
        decoded = fw_api.tmc2209_gstat_decode(found)
        return StepOutcome(
            StepStatus.PASSED,
            f"the driver holds {self.name}, and GSTAT was {_hex(found)} when it "
            f"was claimed",
            Result(
                level=Level.OK,
                summary=f"GSTAT as found, {_hex(found)}",
                note="What the driver went through before this firmware owned "
                "it. Cleared by the bring-up that reported it.",
                fields=_flags(decoded),
            ),
        )

    @bench_api.step
    def verify(self, bench: Any) -> StepOutcome:
        """Read-back."""
        reply = bench.firmware.raw.verify_config(idx=self.idx)
        differing = device_profile.slot_names(reply.mismatched)
        if not reply.agrees:
            return StepOutcome(
                StepStatus.FAILED,
                f"the driver disagrees with what was written: "
                f"{', '.join(differing) or 'no register named'}",
                Result(
                    level=Level.ERROR,
                    summary="the driver holds something else",
                    note="Only GCONF and CHOPCONF read back; the other eight "
                    "owned registers are write-only.",
                    fields=(("mismatched", _hex(reply.mismatched)),),
                ),
            )
        return StepOutcome(
            StepStatus.PASSED,
            "the two registers that read back agree with what was written",
            Result(
                level=Level.OK,
                summary="GCONF and CHOPCONF agree",
                fields=(("mismatched", _hex(reply.mismatched)),),
            ),
        )

    @bench_api.step
    def health(self, bench: Any) -> StepOutcome:
        """Health."""
        reply = bench.firmware.raw.poll_health(idx=self.idx)
        conditions = fw_api.Tmc2209Condition(reply.conditions)
        named = ", ".join(flag.name or "" for flag in conditions) or "nothing reported"
        return StepOutcome(
            StepStatus.WARNED if reply.conditions else StepStatus.PASSED,
            f"health: {named}",
            Result(
                level=Level.WARN if reply.conditions else Level.OK,
                summary=named,
                note="Reported, not judged. Latched conditions survive until "
                "clear_faults acknowledges them, and standstill is normal here.",
                fields=(("conditions", _hex(reply.conditions)),),
            ),
        )

    @bench_api.step
    def cached(self, bench: Any) -> StepOutcome:
        """What it holds."""
        held = {}
        for reg in READ_BACK:
            reply = bench.firmware.raw.read(idx=self.idx, reg=int(reg))
            held[device_profile.register_name(int(reg))] = reply.value

        asked = {device_profile.register_name(op.reg): op.value for op in self.ops}
        rows = tuple(
            (name, _hex(asked[name]), _hex(value)) for name, value in held.items()
        )
        return StepOutcome(
            StepStatus.PASSED,
            ", ".join(f"{name}={_hex(value)}" for name, value in held.items()),
            Result(
                level=Level.OK,
                summary="the driver is configured and standing still",
                table=Table(head=("register", "written", "held"), rows=rows),
            ),
        )
