"""Every firmware method, declared as an action, without writing any of them out.

`fw_api` already generates one annotated dataclass per method from the firmware
headers, and an annotated dataclass is exactly what a form derives from. Writing
twenty-six declarations by hand would copy names and order that are already
fixed elsewhere, and the copy would go stale the day a header changes.

So the declarations are made in a loop. `@action` is a function like any other,
and calling it without the decorator syntax is the same registration.
"""

from __future__ import annotations

import ctypes
import dataclasses
import enum
from collections.abc import Callable
from typing import Any

from shared import bench_api, fw_api
from shared.bench_api import Level, Option, Result, Table, blocked
from shared.bench_api.stef import STEF

SUMMARY = 140
DEVICE = "Which driver, by the name the board declares for it."
REGISTER = "Which register to write, out of the ones the firmware owns."

# The codec that names one register's bits, for each register that has one. The
# rest are plain scalars, where the number is already the answer.
CODEC = {
    fw_api.TMC2209_GCONF: fw_api.tmc2209_gconf_decode,
    fw_api.TMC2209_GSTAT: fw_api.tmc2209_gstat_decode,
    fw_api.TMC2209_IFCNT: fw_api.tmc2209_ifcnt_decode,
    fw_api.TMC2209_IOIN: fw_api.tmc2209_ioin_decode,
    fw_api.TMC2209_IHOLD_IRUN: fw_api.tmc2209_ihold_irun_decode,
    fw_api.TMC2209_VACTUAL: fw_api.tmc2209_vactual_decode,
    fw_api.TMC2209_COOLCONF: fw_api.tmc2209_coolconf_decode,
    fw_api.TMC2209_MSCURACT: fw_api.tmc2209_mscuract_decode,
    fw_api.TMC2209_CHOPCONF: fw_api.tmc2209_chopconf_decode,
    fw_api.TMC2209_DRV_STATUS: fw_api.tmc2209_drv_status_decode,
    fw_api.TMC2209_PWM_SCALE: fw_api.tmc2209_pwm_scale_decode,
    fw_api.TMC2209_PWM_AUTO: fw_api.tmc2209_pwm_auto_decode,
}

# A method whose reply is one register the method itself names.
ANSWERS = {
    "raw.poll_pins": fw_api.TMC2209_IOIN,
}

# A method whose reply is one register the caller named, in this argument.
ANSWERS_WHAT_WAS_ASKED = {"raw.read", "raw.poll_raw"}

HAZARDOUS = {
    "raw.move",
    "raw.retarget",
    "raw.set_velocity",
    "raw.set_current",
    "raw.enable",
    "raw.line_write",
    "raw.write",
    "raw.clear_faults",
    "raw.invalidate_owned",
    "raw.bringup",
    "relay.send",
}


def firmware() -> Any:
    """Return the open link, or say that there is nothing to call through."""
    link = STEF.transport.link
    live = getattr(link, "firmware", None)
    if live is None:
        raise bench_api.DeclarationError("the transport is not connected")
    return live


def connected(*_: Any, **__: Any) -> Any:
    """Say whether a call may be made at all, which is whether the link is up."""
    link = STEF.transport.link
    if getattr(link, "firmware", None) is None:
        return blocked("not connected")
    return None


def devices() -> tuple[Option, ...]:
    """Return the board's driver table, as the names each index stands for.

    Asked rather than declared. The firmware's table carries the names, growing
    the machine is growing that table, and a copy kept here would disagree with
    the board the first time one is added.
    """
    if connected() is not None:
        return ()
    try:
        reply = firmware().sys.devices()
    except Exception:  # noqa: BLE001
        return ()
    return tuple(
        Option(index, _as_text(entry.name) or str(index))
        for index, entry in enumerate(reply.devs)
    )


def owned_registers() -> tuple[Option, ...]:
    """Return the registers a batch may name, which is the ones the firmware owns.

    `tmc2209_write` takes owned registers and refuses the rest, so offering all
    twenty-three is offering a refusal. Which ones those are is asked of the
    library rather than listed here, since the library is what will refuse.

    Asked once, at declaration. The table is compiled into the library, so unlike
    the board's driver table this cannot answer differently later.
    """
    return tuple(
        Option(int(reg), reg.name.removeprefix("TMC2209_"))
        for reg in fw_api.Tmc2209Reg
        if fw_api.tmc2209_reg_class(int(reg)) == fw_api.TMC2209_CLASS_OWNED
    )


def _values(args: Any) -> dict[str, Any]:
    """Return an argument object as the keywords the generated method takes."""
    if args is None:
        return {}
    if dataclasses.is_dataclass(args) and not isinstance(args, type):
        return {f.name: getattr(args, f.name) for f in dataclasses.fields(args)}
    mapping: Any = args
    return dict(mapping)


def text_fields(struct_type: Any) -> frozenset[str]:
    """Return the fields the firmware declared as characters rather than bytes.

    Both read back as `bytes`, so the dataclass alone cannot tell a name from a
    payload. The wire struct can.
    """
    if struct_type is None:
        return frozenset()
    return frozenset(
        name
        for name, ctype, *_ in struct_type._fields_
        if getattr(ctype, "_type_", None) is ctypes.c_char
    )


def as_result(
    name: str, reply: Any, struct: Any = None, register: Any = None
) -> Result:
    """Return whatever a method answered in the one vocabulary every caller reads."""
    if reply is None:
        return Result(level=Level.OK, summary=f"{name} returned")
    if not dataclasses.is_dataclass(reply):
        return Result(level=Level.OK, summary=f"{name} -> {reply}")

    texts = text_fields(struct)
    fields: list[tuple[str, str]] = []
    table: Table | None = None
    for f in dataclasses.fields(reply):
        if f.name.startswith("_"):
            continue
        value = getattr(reply, f.name)
        if isinstance(value, list):
            built = _table(value, _element_texts(struct, f.name))
            if built is not None and table is None:
                table = built
                continue
            fields.append((f.name, f"{len(value)} entries"))
            continue
        if f.name in texts and isinstance(value, bytes):
            fields.append((f.name, _as_text(value)))
            continue
        fields.append((f.name, _render(value)))

    named, note = _decoded(name, reply, ANSWERS.get(name, register))
    shown_fields = named or tuple(fields)

    shown = ", ".join(f"{k}={v}" for k, v in shown_fields)
    if table is not None:
        counted = f"{len(table.rows)} entries"
        shown = f"{shown}, {counted}" if shown else counted
    return Result(
        level=Level.OK,
        summary=_clipped(f"{name} -> {shown}" if shown else name),
        note=note,
        fields=shown_fields,
        table=table,
    )


def asked_register(name: str, args: Any) -> Any | None:
    """Return the register a call asked for, for the methods that answer per register.

    Only these need telling. A method that always answers the same register names
    it in `ANSWERS`, which `as_result` reads for itself, so a caller holding no
    arguments still gets the decode.
    """
    if name in ANSWERS_WHAT_WAS_ASKED:
        return getattr(args, "reg", None)
    return None


def _decoded(
    name: str, reply: Any, register: Any
) -> tuple[tuple[tuple[str, str], ...], str | None]:
    """Return a raw register reply as the named bits it stands for.

    A TMC2209 register is a packed bitfield, so the number that came off the wire
    is the encoding of the answer rather than the answer. The codec that unpacks
    it is generated alongside the ABI and is the one the firmware would have
    used, so running it here costs nothing and leaving it undone makes an
    operator do it by hand against the datasheet.
    """
    label = _register_label(register)
    if label is None:
        return (), None
    raw = getattr(reply, "value", None)
    if not isinstance(raw, int):
        return (), None

    codec = CODEC.get(register)
    if codec is None:
        # A scalar register, where the number is already the answer. Naming it
        # after the register is the whole of what this can add.
        return ((label, _render(raw)),), None

    note = f"{label} 0x{raw:08x}, decoded with the firmware's own codec"
    decoded = codec(raw)
    members = getattr(type(decoded), "_fields_", None)
    if members is None:
        # A codec answering one number rather than a struct, which is the two
        # registers whose width or sign the raw word does not carry.
        return ((label, _render(decoded)),), note
    return tuple(
        (member, _render(getattr(decoded, member)))
        for member, *_ in members
        if not member.startswith("_")
    ), note


def _register_label(register: Any) -> str | None:
    """Return the short name of a register, or None where it names none."""
    if register is None:
        return None
    try:
        return fw_api.Tmc2209Reg(register).name.removeprefix("TMC2209_")
    except ValueError:
        return None


def _as_text(raw: bytes) -> str:
    """Return a fixed-width field as the name it holds, up to its terminator."""
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


def _element_texts(struct: Any, field: str) -> frozenset[str]:
    """Return the character fields of whatever a repeating member holds."""
    flex = fw_api.FLEX.get(struct) if struct is not None else None
    if flex is None or flex.field != field:
        return frozenset()
    return text_fields(flex.elem)


def _table(entries: list[Any], texts: frozenset[str] = frozenset()) -> Table | None:
    """Return a list of records as rows, or None where the list is not records."""
    if not entries or not dataclasses.is_dataclass(entries[0]):
        return None
    head = tuple(f.name for f in dataclasses.fields(entries[0]))
    return Table(
        head=head,
        rows=tuple(
            tuple(_cell(getattr(e, n), n in texts) for n in head) for e in entries
        ),
    )


def _cell(value: Any, is_text: bool) -> str:
    """Return one table cell, reading a character field as the name it holds."""
    if is_text and isinstance(value, bytes):
        return _as_text(value)
    return _render(value)


def _clipped(line: str) -> str:
    """Return a headline short enough to read at a glance."""
    return line if len(line) <= SUMMARY else line[: SUMMARY - 3] + "..."


def _render(value: Any) -> str:
    """Return one decoded field as the text a panel shows."""
    if isinstance(value, enum.Enum):
        label = value.name or str(value)
        if not isinstance(value, int) or label == str(int(value)):
            return label
        return f"{label} ({int(value)})"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, bytes):
        return value.hex(" ") or "(empty)"
    if isinstance(value, int):
        return f"{value} (0x{value:x})" if value > 9 else str(value)
    if isinstance(value, list):
        return f"{len(value)} entries"
    return str(value)


def _caller(spec: fw_api.MethodSpec) -> Callable[[Any], Result]:
    """Return the function that makes one method's call, annotated so a form derives.

    The annotation is the whole declaration: `@action` reads the argument type
    off it, and `derive.py` turns that dataclass into the controls.
    """
    namespace, _, method = spec.name.partition(".")

    def call(args=None):
        bound = getattr(getattr(firmware(), namespace), method)
        reply = bound(**_values(args))
        return as_result(
            spec.name, reply, spec.wire[1], asked_register(spec.name, args)
        )

    call.__name__ = spec.name.replace(".", "_")
    call.__qualname__ = call.__name__
    call.__module__ = __name__
    call.__doc__ = spec.doc or f"Call {spec.name}."
    call.__annotations__ = {} if spec.args is None else {"args": spec.args}
    return call


def _declared(spec: fw_api.MethodSpec) -> tuple[Any, ...]:
    """Return the residue an annotation cannot carry, for the fields that have any.

    An index is a number until the board says which driver each one is, and a
    batch element names a register out of a set narrower than the type allows.
    """
    params: list[Any] = []
    if "idx" in spec.fields:
        params.append(bench_api.choice("idx", devices, hint=DEVICE))
    if "ops" in spec.fields:
        params.append(
            bench_api.group(
                "ops",
                columns=(
                    bench_api.integer("value"),
                    bench_api.choice("reg", owned_registers(), hint=REGISTER),
                ),
            )
        )
    return tuple(params)


def declare() -> tuple[str, ...]:
    """Register one action per generated method, and return what was registered."""
    declared = []
    for namespace in fw_api.namespaces().values():
        for spec in namespace.values():
            bench_api.action(
                spec.name,
                hazardous=spec.name in HAZARDOUS,
                precondition=connected,
                params=_declared(spec),
            )(_caller(spec))
            declared.append(spec.name)
    return tuple(declared)


NAMES = declare()
