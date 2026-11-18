"""One diagnostics command per firmware method, built from the dataclasses `fw_api` generates."""

import ctypes
import dataclasses
import enum
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from shared import fw_api
from shared.diagnostics import Command
from shared.subsystem import (
    Level,
    LinkState,
    Option,
    Result,
    Table,
    choice,
    group,
    inputs_for,
    integer,
    overridden,
    summary_and_body,
    titled,
)

if TYPE_CHECKING:
    from transport.subsystem import Transport

SUMMARY_MAX_CHARS = 140
DEVICE_HINT = "The driver to use."
REGISTER_HINT = "The register to write. Only registers the firmware owns are listed."

# Decoders for the registers made of bitfields.
REGISTER_DECODERS = {
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

# Methods whose reply is always the same register.
REPLY_REGISTER_BY_METHOD = {"raw.poll_pins": fw_api.TMC2209_IOIN}

# Methods whose reply is the register named in their `reg` argument.
REPLY_REGISTER_IN_ARGS = {"raw.read", "raw.poll_raw"}

# relay sends hand-built datagrams. Everything an operator needs is in raw.
SKIPPED_NAMESPACES = ("relay",)

HAZARDS = {
    "raw.move": "turns the shaft",
    "raw.retarget": "changes the speed of a running move",
    "raw.set_velocity": "turns the shaft until the velocity is set back to 0",
    "raw.set_current": "changes the coil current",
    "raw.enable": "switches the power stage on or off",
    "raw.line_write": "drives a pin with no checks",
    "raw.write": "writes driver registers",
    "raw.clear_faults": "stops reporting latched faults",
    "raw.invalidate_owned": "marks the register cache invalid",
    "raw.bringup": "writes the whole driver configuration",
}


def driver_options(transport: Transport | None) -> tuple[Option, ...]:
    """Return the board's drivers as options, or none when the board cannot be asked."""
    if transport is None or transport.link_state() is not LinkState.UP:
        return ()
    try:
        reply = transport.firmware().sys.devices()
    except Exception:  # noqa: BLE001
        return ()
    return tuple(
        Option(index, _c_string(entry.name) or str(index))
        for index, entry in enumerate(reply.devs)
    )


def owned_register_options() -> tuple[Option, ...]:
    """Return the registers the firmware owns as options."""
    return tuple(
        Option(int(register), register.name.removeprefix("TMC2209_"))
        for register in fw_api.Tmc2209Reg
        if fw_api.tmc2209_reg_class(int(register)) == fw_api.TMC2209_CLASS_OWNED
    )


def reply_result(
    method_name: str, reply: Any, reply_struct: type | None, register: int | None
) -> Result:
    """Return a method's reply as a summary line, its fields, and a table for a list of records.

    A reply that is one register is shown as that register's decoded fields.
    """
    if reply is None:
        return Result(level=Level.OK, summary=f"{method_name} returned")
    if not dataclasses.is_dataclass(reply):
        return Result(level=Level.OK, summary=f"{method_name} -> {reply}")

    text_names = _char_fields(reply_struct)
    fields: list[tuple[str, str]] = []
    table: Table | None = None
    for field in dataclasses.fields(reply):
        if field.name.startswith("_"):
            continue
        value = getattr(reply, field.name)
        if isinstance(value, list):
            records = _records_table(value, _flex_char_fields(reply_struct, field.name))
            if records is not None and table is None:
                table = records
                continue
            fields.append((field.name, f"{len(value)} entries"))
            continue
        if field.name in text_names and isinstance(value, bytes):
            fields.append((field.name, _c_string(value)))
            continue
        fields.append((field.name, _field_text(value)))

    register_fields, note = _register_fields(reply, register)
    shown = register_fields or tuple(fields)

    line = ", ".join(f"{label}={text}" for label, text in shown)
    if table is not None:
        counted = f"{len(table.rows)} entries"
        line = f"{line}, {counted}" if line else counted
    return Result(
        level=Level.OK,
        summary=_clipped(f"{method_name} -> {line}" if line else method_name),
        note=note,
        fields=shown,
        table=table,
    )


def reply_register(method_name: str, arguments: dict[str, Any]) -> int | None:
    """Return the register a method's reply holds, or None when it holds none."""
    if method_name in REPLY_REGISTER_IN_ARGS:
        return arguments.get("reg")
    return REPLY_REGISTER_BY_METHOD.get(method_name)


def _register_fields(
    reply: Any, register: int | None
) -> tuple[tuple[tuple[str, str], ...], str | None]:
    """Return a register reply as its decoded fields, with the raw word as a note."""
    label = _register_name(register)
    if label is None:
        return (), None
    word = getattr(reply, "value", None)
    if not isinstance(word, int):
        return (), None

    decoder = REGISTER_DECODERS.get(register)
    if decoder is None:
        return ((label, _field_text(word)),), None

    note = f"{label} = 0x{word:08x}"
    decoded = decoder(word)
    members = getattr(type(decoded), "_fields_", None)
    if members is None:
        # VACTUAL and IFCNT decode to one number.
        return ((label, _field_text(decoded)),), note
    return tuple(
        (member, _field_text(getattr(decoded, member)))
        for member, *_ in members
        if not member.startswith("_")
    ), note


def _register_name(register: int | None) -> str | None:
    """Return a register's name without the TMC2209_ prefix, or None if it is not one."""
    if register is None:
        return None
    try:
        return fw_api.Tmc2209Reg(register).name.removeprefix("TMC2209_")
    except ValueError:
        return None


def _char_fields(struct: Any) -> frozenset[str]:
    """Return the names of a ctypes struct's `char` array fields, which hold text."""
    if struct is None:
        return frozenset()
    return frozenset(
        name
        for name, ctype, *_ in struct._fields_
        if getattr(ctype, "_type_", None) is ctypes.c_char
    )


def _flex_char_fields(struct: type | None, field: str) -> frozenset[str]:
    """Return the `char` fields of the records in `field`, if it is the struct's flexible array."""
    flexible = fw_api.FLEX.get(struct) if struct is not None else None
    if flexible is None or flexible.field != field:
        return frozenset()
    return _char_fields(flexible.elem)


def _c_string(chars: bytes) -> str:
    """Return a fixed-width `char` field up to its terminator."""
    return chars.split(b"\0", 1)[0].decode("utf-8", "replace")


def _records_table(
    entries: list[Any], text_names: frozenset[str] = frozenset()
) -> Table | None:
    """Return a list of records as a table, or None when the list holds no records."""
    if not entries or not dataclasses.is_dataclass(entries[0]):
        return None
    head = tuple(f.name for f in dataclasses.fields(entries[0]))
    return Table(
        head=head,
        rows=tuple(
            tuple(
                _cell(getattr(entry, column), column in text_names) for column in head
            )
            for entry in entries
        ),
    )


def _cell(value: Any, is_text: bool) -> str:
    """Return one table cell."""
    if is_text and isinstance(value, bytes):
        return _c_string(value)
    return _field_text(value)


def _clipped(line: str) -> str:
    """Return the line cut to SUMMARY_MAX_CHARS."""
    if len(line) <= SUMMARY_MAX_CHARS:
        return line
    return line[: SUMMARY_MAX_CHARS - 3] + "..."


def _field_text(value: Any) -> str:
    """Return a field as panel text: enums by name, bytes in hex, ints above 9 also in hex."""
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


# ── One command per method ───────────────────────────────────────────────────


def _command_call(
    spec: fw_api.MethodSpec,
) -> Callable[[Transport, dict[str, Any]], Result]:
    """Return the function that calls one method on the board and reports its reply."""
    namespace, _, method = spec.name.partition(".")

    def call(transport: Transport, arguments: dict[str, Any]) -> Result:
        method_call = getattr(getattr(transport.firmware(), namespace), method)
        reply = method_call(**arguments)
        return reply_result(
            spec.name, reply, spec.ret_layout, reply_register(spec.name, arguments)
        )

    return call


def _command_inputs(spec: fw_api.MethodSpec) -> tuple[Any, ...]:
    """Return a method's form, with `idx` as a driver choice and `ops` limited to owned registers."""
    overrides = {
        "idx": choice("idx", driver_options, hint=DEVICE_HINT),
        "ops": group(
            "ops",
            columns=(
                integer("value"),
                choice("reg", owned_register_options(), hint=REGISTER_HINT),
            ),
        ),
    }
    derived = inputs_for(spec.args)
    applicable = {
        field: control for field, control in overrides.items() if field in spec.fields
    }
    return overridden(derived, applicable)


def _commands() -> tuple[Command, ...]:
    """Return one command per method, except those in SKIPPED_NAMESPACES."""
    commands = []
    for namespace, methods in fw_api.namespaces().items():
        if namespace in SKIPPED_NAMESPACES:
            continue
        for method, spec in methods.items():
            summary, body = summary_and_body(spec.doc or "")
            commands.append(
                Command(
                    group=namespace,
                    name=method,
                    title=titled(summary) or spec.name,
                    description=body,
                    call=_command_call(spec),
                    inputs=_command_inputs(spec),
                    hazard=HAZARDS.get(spec.name),
                )
            )
    return tuple(commands)


COMMANDS = _commands()
