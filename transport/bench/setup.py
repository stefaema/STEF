"""What an operator does to a driver once the link is up."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared import fw_api
from shared.diagnostics import Failed, Test, step
from shared.subsystem import Level, Result, Table, choice
from transport import device_profile
from transport.bench.calls import DEVICE, devices

if TYPE_CHECKING:
    from transport.subsystem import Transport

PROFILE = "Profile"
BRING_UP = "Bring-up"
READ_BACK = "Read-back"
HEALTH = "Health"
CACHED_REGISTERS = "Cached registers"

CACHED = (fw_api.TMC2209_GCONF, fw_api.TMC2209_CHOPCONF)

# What a driver reports at the end of a bring-up that is not news. Standing
# still is the state this routine leaves it in, and open load is measured off
# the coil current, so with the motor stopped it reports the stillness rather
# than the wiring.
EXPECTED = fw_api.TMC2209_STANDSTILL | fw_api.TMC2209_OPEN_LOAD


def hex_word(value: int) -> str:
    """Return one register word as it is written in a datasheet."""
    return f"0x{value & 0xFFFFFFFF:08x}"


def flag_rows(decoded: Any) -> tuple[tuple[str, str], ...]:
    """Return a decoded register as the named bits it stands for."""
    return tuple(
        (
            name,
            "true" if value is True else "false" if value is False else str(int(value)),
        )
        for name, *_ in type(decoded)._fields_
        if not name.startswith("_")
        for value in (getattr(decoded, name),)
    )


def named_conditions(conditions: fw_api.Tmc2209Condition) -> str:
    """Return what poll_health reported, in the datasheet's words."""
    return ", ".join(
        flag.name.removeprefix("TMC2209_") for flag in conditions if flag.name
    )


def _written(ops: tuple[Any, ...]) -> Table:
    """Return what is about to go on the wire, one row per owned register."""
    return Table(
        head=("register", "value"),
        rows=tuple(
            (device_profile.register_name(op.reg), hex_word(op.value)) for op in ops
        ),
    )


# ── Bringing one driver up ───────────────────────────────────────────────────


class BaselineBringup(Test[Any]):
    """Bring a driver up to its baseline.

    Writes one configuration profile onto a driver and asks what it made of it.
    Ends with the driver holding every owned register, standing still, and its
    power stage untouched.

    A baseline is tuned for no load in particular. It is what proves the driver,
    the wiring and the link work, and it is where a profile for a real load
    starts.
    """

    sub: Transport
    inputs = (
        choice("idx", devices, hint=DEVICE),
        choice(
            "profile",
            lambda sub: device_profile.names(),
            hint="Which profile to write, out of the ones installed here.",
        ),
    )

    @step(PROFILE)
    def profile(self) -> None:
        self.raw = self.sub.firmware().raw
        self.idx = self.values["idx"]
        name = self.values["profile"]
        try:
            self.ops = device_profile.ops(device_profile.load(name))
        except Exception as exc:
            raise Failed(
                f"{name} is not a configuration this driver can be given: {exc}"
            ) from exc
        self.report(
            f"{name} covers all {len(self.ops)} owned registers",
            Result(
                level=Level.OK,
                summary=f"{name}, as the firmware's own codecs encode it",
                fields=(("profile", name),),
                table=_written(self.ops),
            ),
        )

    @step(BRING_UP, hazard="rewrites every owned register")
    def bring_up(self) -> None:
        name = self.values["profile"]
        found = self.raw.bringup(idx=self.idx, ops=list(self.ops)).gstat_found
        self.report(
            f"the driver holds {name}, and GSTAT was {hex_word(found)} when it was claimed",
            Result(
                level=Level.OK,
                summary=f"GSTAT as found, {hex_word(found)}",
                note="What the driver went through before this firmware owned it. "
                "Cleared by the bring-up that reported it.",
                fields=flag_rows(fw_api.tmc2209_gstat_decode(found)),
            ),
        )

    @step(READ_BACK)
    def read_back(self) -> None:
        agreed = self.raw.verify_config(idx=self.idx)
        if not agreed.agrees:
            differing = ", ".join(device_profile.slot_names(agreed.mismatched))
            raise Failed(
                f"the driver disagrees with what was written: {differing or 'no register named'}",
                Result(
                    level=Level.ERROR,
                    summary="the driver holds something else",
                    note="Only GCONF and CHOPCONF read back; the other eight owned "
                    "registers are write-only.",
                    fields=(("mismatched", hex_word(agreed.mismatched)),),
                ),
            )
        self.report(
            "the two registers that read back agree with what was written",
            Result(
                level=Level.OK,
                summary="GCONF and CHOPCONF agree",
                fields=(("mismatched", hex_word(agreed.mismatched)),),
            ),
        )

    @step(HEALTH)
    def health(self) -> None:
        conditions = fw_api.Tmc2209Condition(
            self.raw.poll_health(idx=self.idx).conditions
        )
        unexpected = conditions & ~EXPECTED
        if unexpected:
            summary = named_conditions(unexpected)
        elif conditions:
            summary = f"{named_conditions(conditions)}, which is what a driver at rest reports"
        else:
            summary = "nothing reported"
        said = self.warn if unexpected else self.report
        said(
            f"health: {named_conditions(conditions) or 'nothing reported'}",
            Result(
                level=Level.WARN if unexpected else Level.OK,
                summary=summary,
                note="Reported, not judged. Latched conditions survive until "
                "clear_faults acknowledges them. Standstill and open load are what "
                "a stopped driver reports, so neither is held against it here.",
                fields=(("conditions", hex_word(int(conditions))),),
            ),
        )

    @step(CACHED_REGISTERS)
    def cached_registers(self) -> None:
        rows = tuple(
            (
                device_profile.register_name(int(reg)),
                hex_word(self.raw.read(idx=self.idx, reg=int(reg)).value),
            )
            for reg in CACHED
        )
        self.report(
            ", ".join(f"{name} holds {value}" for name, value in rows),
            Result(
                level=Level.OK,
                summary="what the firmware caches for the registers that read back",
                table=Table(head=("register", "value"), rows=rows),
            ),
        )
