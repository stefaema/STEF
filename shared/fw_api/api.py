"""The callable surface the ABI implies: namespaces, methods, and their payloads."""

import ctypes
import dataclasses
import enum
from typing import Any, NamedTuple

from shared.fw_api import abi

# ── How this fails ───────────────────────────────────────────────────────────


class FwError(Exception):
    """Anything this package raises for itself, as opposed to what the board says."""


class ApiError(FwError):
    """A payload that does not agree with the type it claims to be."""


# ── Payloads that end in a flexible array ────────────────────────────────────


def _array(elem: Any, count: int) -> Any:
    """Return the ctypes array type for the element and count given."""
    return elem * count


def pack(struct_type: type, values: dict[str, Any]) -> bytes:
    """Return the payload bytes, sizing any flexible member from its sequence."""
    flex = abi.FLEX.get(struct_type)
    if flex is None:
        return bytes(struct_type(**values))

    values = dict(values)
    items = list(values.pop(flex.field, ()))
    head = struct_type(**values)
    setattr(head, flex.count_field, len(items))
    return bytes(head) + bytes(_array(flex.elem, len(items))(*items))


def unpack(struct_type: type, payload: bytes) -> Any:
    """Return the payload as its struct, with a flexible member attached."""
    base = ctypes.sizeof(struct_type)
    if len(payload) < base:
        payload = payload + bytes(base - len(payload))

    head = struct_type.from_buffer_copy(payload[:base])
    flex = abi.FLEX.get(struct_type)
    if flex is not None:
        count = getattr(head, flex.count_field)
        width = ctypes.sizeof(flex.elem)
        tail = payload[base : base + count * width]
        if len(tail) != count * width:
            raise ApiError(f"{struct_type.__name__} claims {count} it did not send")
        setattr(head, flex.field, list(_array(flex.elem, count).from_buffer_copy(tail)))
    return head


# ── The same payloads, as Python rather than as ctypes ───────────────────────
#
# ctypes lays out the bytes and nothing more. Every value crossing this surface
# is a bool, an int, an enum member, bytes, a list or one of these dataclasses.
#
# What each field becomes is read off SEMANTIC: `idx` and `dir` are both
# uint8_t, and only the typedef says one indexes a table and the other is a
# pin level.

BOOL = "rpc_bool_t"
PAD = "_pad"

_DATACLASSES: dict[type, type] = {}


def _is_byte_array(ctype: Any) -> bool:
    """Whether the ctypes array holds single bytes, and so reads back as bytes."""
    elem = getattr(ctype, "_type_", None)
    return elem is not None and ctypes.sizeof(elem) == 1 and not _is_record(elem)


def _is_record(ctype: Any) -> bool:
    """Whether the ctypes type is a struct or a union, and so has its own dataclass."""
    return isinstance(ctype, type) and issubclass(
        ctype, (ctypes.Structure, ctypes.Union)
    )


def _python_type(struct_type: type, name: str, ctype: Any) -> Any:
    """Return the Python type one field carries, from what the C declared it as."""
    written = abi.SEMANTIC.get(struct_type, {}).get(name)
    if written == BOOL:
        return bool
    if written in abi.PY_ENUM:
        return abi.PY_ENUM[written]
    if ctype is ctypes.c_bool:
        return bool
    if _is_record(ctype):
        return dataclass_for(ctype)
    if getattr(ctype, "_length_", None) is not None:
        elem = ctype._type_
        return bytes if _is_byte_array(ctype) else list[dataclass_for(elem)]
    return int


def _flex_type(elem: Any) -> Any:
    """Return what a flexible member reads back as: bytes of them, or a list of them."""
    if _is_record(elem):
        return list[dataclass_for(elem)]
    return bytes if ctypes.sizeof(elem) == 1 else list[int]


def python_name(struct_type: type) -> str:
    """Return the dataclass name a payload is known by.

    Spelled here, not in the generator, so a rename never touches a generated file.
    """
    stem = struct_type.__name__.removeprefix("rpc_").removesuffix("_t")
    return "".join(part.capitalize() for part in stem.split("_"))


def dataclass_for(struct_type: type) -> type:
    """Return the dataclass mirroring one payload, its fields in wire order.

    Padding is a property of the layout, not of the message, so it is gone. So
    is a flexible member's count: the list already knows how long it is.
    """
    known = _DATACLASSES.get(struct_type)
    if known is not None:
        return known

    # Registered before its fields are built, so a record holding itself ends.
    placeholder = dataclasses.make_dataclass(python_name(struct_type), [])
    _DATACLASSES[struct_type] = placeholder

    flex = abi.FLEX.get(struct_type)
    fields: list[tuple[str, Any, Any]] = []
    for name, ctype, *_ in struct_type._fields_:
        if name.startswith(PAD):
            continue
        if flex is not None and name == flex.count_field:
            continue
        want = _python_type(struct_type, name, ctype)
        fields.append((name, want, _default_for(want, ctype)))
    if flex is not None:
        want = _flex_type(flex.elem)
        fields.append((flex.field, want, _default_for(want, None)))

    built = dataclasses.make_dataclass(python_name(struct_type), fields)
    built.__doc__ = struct_type.__doc__
    _DATACLASSES[struct_type] = built
    return built


def _default_for(want: Any, ctype: Any) -> Any:
    """Return the field's default, which is what zeroed bytes decode to."""
    if want is bool:
        return dataclasses.field(default=False)
    if want is bytes:
        length = getattr(ctype, "_length_", 0)
        # A fixed array reads back whole; a flexible member has nothing yet.
        empty = (
            bytes(length)
            if ctype is not None and ctype._type_ is not ctypes.c_char
            else b""
        )
        return dataclasses.field(default=empty)
    if want is int:
        return dataclasses.field(default=0)
    if isinstance(want, type) and issubclass(want, enum.IntEnum | enum.IntFlag):
        zero = next((m for m in want if int(m) == 0), None)
        return dataclasses.field(default=zero if zero is not None else want(0))
    if isinstance(want, type) and dataclasses.is_dataclass(want):
        return dataclasses.field(default_factory=want)
    return dataclasses.field(default_factory=list)


def _to_wire(value: Any) -> Any:
    """Return the value as ctypes will take it, which is an int for everything named."""
    if isinstance(value, enum.IntEnum | enum.IntFlag):
        return int(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _from_wire(want: Any, value: Any) -> Any:
    """Return what came out of ctypes as the type the dataclass promises."""
    if want is bool:
        return bool(value)
    if isinstance(want, type) and issubclass(want, enum.IntEnum | enum.IntFlag):
        return want(value)
    if want is bytes:
        return bytes(value)
    if isinstance(want, type) and dataclasses.is_dataclass(want):
        return _read_record(want, value)
    origin = getattr(want, "__origin__", None)
    if origin is list:
        (item,) = want.__args__
        return [_from_wire(item, entry) for entry in value]
    return value


def _read_record(target: type, struct: Any) -> Any:
    """Return the dataclass holding what one ctypes struct carries."""
    hints = {f.name: f.type for f in dataclasses.fields(target)}
    return target(
        **{
            name: _from_wire(want, getattr(struct, name))
            for name, want in hints.items()
        }
    )


def _to_field(ctype: Any, value: Any) -> Any:
    """Return one value as the ctypes field it is about to be written into takes it."""
    if _is_record(ctype):
        return ctype(**_wire_values(ctype, value))
    length = getattr(ctype, "_length_", None)
    if length is not None and ctype._type_ is not ctypes.c_char:
        return ctype(*bytes(value)[:length])
    return _to_wire(value)


def _wire_values(struct_type: type, payload: Any) -> dict[str, Any]:
    """Return the dataclass's fields keyed and typed the way pack() will place them."""
    declared = {name: ctype for name, ctype, *_ in struct_type._fields_}
    flex = abi.FLEX.get(struct_type)
    values: dict[str, Any] = {}
    for f in dataclasses.fields(payload):
        value = getattr(payload, f.name)
        if flex is not None and f.name == flex.field:
            values[f.name] = _encode_flex(flex.elem, value)
        else:
            values[f.name] = _to_field(declared[f.name], value)
    return values


def encode(struct_type: type, payload: Any) -> bytes:
    """Return the wire bytes for one payload dataclass."""
    return pack(struct_type, _wire_values(struct_type, payload))


def _encode_flex(elem: Any, value: Any) -> Any:
    """Return a flexible member's items as the ctypes element type takes them."""
    if _is_record(elem):
        return [elem(**_wire_values(elem, item)) for item in value]
    return list(value)


def decode(struct_type: type, payload: bytes) -> Any:
    """Return the payload bytes as the dataclass this type stands for."""
    return _read_record(dataclass_for(struct_type), unpack(struct_type, payload))


# ── The surface derived from the enums ───────────────────────────────────────


class MethodSpec(NamedTuple):
    """One callable method, and the payload types its own name predicts."""

    name: str
    ns: int
    method: int
    args: type | None
    ret: type | None
    fields: tuple[str, ...]
    wire: tuple[type | None, type | None] = (None, None)


def _positional_fields(args_type: type | None) -> tuple[str, ...]:
    """Return the arguments a caller may pass by position, in order."""
    if args_type is None:
        return ()
    return tuple(f.name for f in dataclasses.fields(args_type))


def _methods(stem: str, ns: int, method_enum: Any) -> dict[str, MethodSpec]:
    """Return one namespace's methods, keyed by the name they answer to."""
    specs: dict[str, MethodSpec] = {}
    for member in method_enum:
        if member.name.endswith("_COUNT"):
            continue
        payload_stem = member.name.lower()
        args_wire = getattr(abi, f"{payload_stem}_args", None)
        ret_wire = getattr(abi, f"{payload_stem}_ret", None)
        args = None if args_wire is None else dataclass_for(args_wire)
        ret = None if ret_wire is None else dataclass_for(ret_wire)
        attr = member.name.removeprefix(f"RPC_{stem}_").lower()
        specs[attr] = MethodSpec(
            name=f"{stem.lower()}.{attr}",
            ns=ns,
            method=int(member),
            args=args,
            ret=ret,
            fields=_positional_fields(args),
            wire=(args_wire, ret_wire),
        )
    return specs


def namespaces() -> dict[str, dict[str, MethodSpec]]:
    """Return every namespace that has methods, derived from the enums."""
    found: dict[str, dict[str, MethodSpec]] = {}
    for member in abi.rpc_ns_t:
        if member.name.endswith("_COUNT"):
            continue
        stem = member.name.removeprefix("RPC_NS_")
        method_enum = getattr(abi, f"rpc_{stem.lower()}_method_t", None)
        if method_enum is None:
            continue
        found[stem.lower()] = _methods(stem, int(member), method_enum)
    return found


# ── Calling one ──────────────────────────────────────────────────────────────


def arguments(spec: MethodSpec, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    """Return the request payload for these arguments, positional or named."""
    if len(args) > len(spec.fields):
        raise TypeError(
            f"{spec.name} takes {len(spec.fields)} arguments, got {len(args)}"
        )

    values = dict(zip(spec.fields, args, strict=False))
    for name in kwargs:
        if name in values:
            raise TypeError(f"{spec.name} got {name} twice")
    values.update(kwargs)

    unknown = set(values) - set(spec.fields)
    if unknown:
        raise TypeError(f"{spec.name} has no argument {', '.join(sorted(unknown))}")

    struct_type, _ = spec.wire
    if spec.args is None or struct_type is None:
        return b""
    return encode(struct_type, spec.args(**values))


def result(spec: MethodSpec, payload: bytes) -> Any:
    """Return what the reply carried, as the dataclass this method promises."""
    _, struct_type = spec.wire
    if spec.ret is None or struct_type is None:
        return None
    return decode(struct_type, payload)


class Namespace:
    """One namespace's methods, reached as attributes of whatever carries them."""

    def __init__(self, carry: Any, specs: dict[str, MethodSpec]) -> None:
        """Bind these methods to the callable that will carry them."""
        self._carry = carry
        self._specs = specs

    def __getattr__(self, name: str) -> Any:
        """Return the named method, bound to its carrier, or say there is none."""
        spec = self._specs.get(name)
        if spec is None:
            raise AttributeError(name)

        def bound(*args: Any, **kwargs: Any) -> Any:
            """Send this method's request and return what the reply carried."""
            return self._carry(spec, args, kwargs)

        bound.__name__ = name
        return bound

    def __dir__(self) -> list[str]:
        """Return the attributes plus every method name, so completion sees them."""
        return [*super().__dir__(), *self._specs]


def attach(carry: Any) -> dict[str, Namespace]:
    """Return every namespace the ABI declares, bound to the given carrier."""
    return {name: Namespace(carry, specs) for name, specs in namespaces().items()}


# ── Everything the ABI already names ─────────────────────────────────────────


def __getattr__(name: str) -> Any:
    """Relay whatever this module does not define to the generated ABI."""
    return getattr(abi, name)


def __dir__() -> list[str]:
    """Return this module's own names plus everything the ABI carries."""
    return sorted({*globals(), *vars(abi)})
