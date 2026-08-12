"""What an operator does to a driver once the link is up."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from shared import bench_api, fw_api
from shared.bench_api import (
    FAILED,
    PASSED,
    WARNED,
    Abandoned,
    Level,
    Result,
    StepOutcome,
    Table,
)
from transport import device_profile, transport
from transport.bench.calls import DEVICE, devices

PROFILE = "Profile"
BRING_UP = "Bring-up"
READ_BACK = "Read-back"
HEALTH = "Health"

CACHED = (fw_api.TMC2209_GCONF, fw_api.TMC2209_CHOPCONF)

# What a driver reports at the end of a bring-up that is not news. Standing
# still is the state this routine leaves it in, and open load is measured off
# the coil current, so with the motor stopped it reports the stillness rather
# than the wiring.
EXPECTED = fw_api.TMC2209_STANDSTILL | fw_api.TMC2209_OPEN_LOAD


def _hex(value: int) -> str:
    """Return one register word as it is written in a datasheet."""
    return f"0x{value & 0xFFFFFFFF:08x}"


def _flags(decoded: Any) -> tuple[tuple[str, str], ...]:
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


def _named(conditions: fw_api.Tmc2209Condition) -> str:
    """Return what poll_health reported, in the datasheet's words."""
    return ", ".join(
        flag.name.removeprefix("TMC2209_") for flag in conditions if flag.name
    )


def _written(ops: tuple[Any, ...]) -> Table:
    """Return what is about to go on the wire, one row per owned register."""
    return Table(
        head=("register", "value"),
        rows=tuple(
            (device_profile.register_name(op.reg), _hex(op.value)) for op in ops
        ),
    )


# ── Bringing one driver up ───────────────────────────────────────────────────


@bench_api.routine(
    hazardous=True,
    steps=[PROFILE, BRING_UP, READ_BACK, HEALTH],
    inputs=[
        bench_api.choice("idx", devices, hint=DEVICE),
        bench_api.choice(
            "profile",
            device_profile.names,
            hint="Which profile to write, out of the ones installed here.",
        ),
    ],
)
def baseline_bringup(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Bring a driver up to its baseline.

    Writes one configuration profile onto a driver and asks what it made of it.
    Ends with the driver holding every owned register, standing still, and its
    power stage untouched.

    A baseline is tuned for no load in particular. It is what proves the driver,
    the wiring and the link work, and it is where a profile for a real load
    starts.
    """
    raw = transport.firmware().raw
    idx = values["idx"]
    name = values["profile"]

    try:
        ops = device_profile.ops(device_profile.load(name))
    except Exception as exc:
        raise Abandoned(
            f"{name} is not a configuration this driver can be given: {exc}", FAILED
        ) from exc
    yield StepOutcome(
        PASSED,
        f"{name} covers all {len(ops)} owned registers",
        Result(
            level=Level.OK,
            summary=f"{name}, as the firmware's own codecs encode it",
            fields=(("profile", name),),
            table=_written(ops),
        ),
        step=PROFILE,
    )

    found = raw.bringup(idx=idx, ops=list(ops)).gstat_at_bringup
    yield StepOutcome(
        PASSED,
        f"the driver holds {name}, and GSTAT was {_hex(found)} when it was claimed",
        Result(
            level=Level.OK,
            summary=f"GSTAT as found, {_hex(found)}",
            note="What the driver went through before this firmware owned it. "
            "Cleared by the bring-up that reported it.",
            fields=_flags(fw_api.tmc2209_gstat_decode(found)),
        ),
        step=BRING_UP,
    )

    agreed = raw.verify_config(idx=idx)
    if not agreed.agrees:
        differing = ", ".join(device_profile.slot_names(agreed.mismatched))
        raise Abandoned(
            f"the driver disagrees with what was written: {differing or 'no register named'}",
            FAILED,
            Result(
                level=Level.ERROR,
                summary="the driver holds something else",
                note="Only GCONF and CHOPCONF read back; the other eight owned "
                "registers are write-only.",
                fields=(("mismatched", _hex(agreed.mismatched)),),
            ),
        )
    yield StepOutcome(
        PASSED,
        "the two registers that read back agree with what was written",
        Result(
            level=Level.OK,
            summary="GCONF and CHOPCONF agree",
            fields=(("mismatched", _hex(agreed.mismatched)),),
        ),
        step=READ_BACK,
    )

    conditions = fw_api.Tmc2209Condition(raw.poll_health(idx=idx).conditions)
    unexpected = conditions & ~EXPECTED
    if unexpected:
        summary = _named(unexpected)
    elif conditions:
        summary = f"{_named(conditions)}, which is what a driver at rest reports"
    else:
        summary = "nothing reported"
    yield StepOutcome(
        WARNED if unexpected else PASSED,
        f"health: {_named(conditions) or 'nothing reported'}",
        Result(
            level=Level.WARN if unexpected else Level.OK,
            summary=summary,
            note="Reported, not judged. Latched conditions survive until "
            "clear_faults acknowledges them. Standstill and open load are what "
            "a stopped driver reports, so neither is held against it here.",
            fields=(("conditions", _hex(int(conditions))),),
        ),
        step=HEALTH,
    )

    for reg in CACHED:
        held = raw.read(idx=idx, reg=int(reg)).value
        yield StepOutcome(
            PASSED, f"{device_profile.register_name(int(reg))} holds {_hex(held)}"
        )
