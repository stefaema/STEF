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
from shared.bench_api import Level, Result, Table, blocked
from shared.bench_api.stef import STEF

SUMMARY = 140
DEVICE = "Which driver, by the name the board declares for it."

# A reply that carries one register and nothing else, and the codec that names
# its bits. `read` and `poll_raw` are absent on purpose: which register they
# answered is an argument, not a property of the method.
DECODED = {
    "raw.poll_pins": ("value", fw_api.tmc2209_ioin_decode),
}

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


def devices() -> tuple[tuple[int, str], ...]:
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
        (index, _as_text(entry.name) or str(index))
        for index, entry in enumerate(reply.devs)
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


def as_result(name: str, reply: Any, struct: Any = None) -> Result:
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

    named, note = _decoded(name, reply)
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


def _decoded(name: str, reply: Any) -> tuple[tuple[tuple[str, str], ...], str | None]:
    """Return a raw register reply as the named bits it stands for.

    `rpc_raw_poll_pins_ret` says it carries IOIN as it came off the wire and
    that the PC decodes it with the same codec the firmware would have used. The
    codec is generated alongside the ABI, so running it here costs nothing and
    showing the number alone would make an operator do it by hand.
    """
    entry = DECODED.get(name)
    if entry is None:
        return (), None
    field, decoder = entry
    raw = getattr(reply, field, None)
    if not isinstance(raw, int):
        return (), None
    struct = decoder(raw)
    fields = tuple(
        (member, _render(getattr(struct, member)))
        for member, *_ in type(struct)._fields_
        if not member.startswith("_")
    )
    return fields, f"{field} 0x{raw:08x}, decoded with the firmware's own codec"


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
        return as_result(spec.name, bound(**_values(args)), spec.wire[1])

    call.__name__ = spec.name.replace(".", "_")
    call.__qualname__ = call.__name__
    call.__module__ = __name__
    call.__doc__ = spec.doc or f"Call {spec.name}."
    call.__annotations__ = {} if spec.args is None else {"args": spec.args}
    return call


def declare() -> tuple[str, ...]:
    """Register one action per generated method, and return what was registered."""
    declared = []
    for namespace in fw_api.namespaces().values():
        for spec in namespace.values():
            bench_api.action(
                spec.name,
                hazardous=spec.name in HAZARDOUS,
                precondition=connected,
                params=(
                    (bench_api.choice("idx", devices, hint=DEVICE),)
                    if "idx" in spec.fields
                    else ()
                ),
            )(_caller(spec))
            declared.append(spec.name)
    return tuple(declared)


NAMES = declare()
