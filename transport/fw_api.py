"""The callable surface the ABI implies: namespaces, methods, and their payloads."""

import ctypes
from typing import Any, NamedTuple

from transport import fw_abi

# ── How this fails ───────────────────────────────────────────────────────────


class TransportError(Exception):
    """Anything this package raises for itself, as opposed to what the board says."""


class ApiError(TransportError):
    """A payload that does not agree with the type it claims to be."""


# ── Payloads that end in a flexible array ────────────────────────────────────


def _array(elem: Any, count: int) -> Any:
    """Return the ctypes array type for the element and count given."""
    return elem * count


def pack(struct_type: type, values: dict[str, Any]) -> bytes:
    """Return the payload bytes, sizing any flexible member from its sequence."""
    flex = fw_abi.FLEX.get(struct_type)
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
    flex = fw_abi.FLEX.get(struct_type)
    if flex is not None:
        count = getattr(head, flex.count_field)
        width = ctypes.sizeof(flex.elem)
        tail = payload[base : base + count * width]
        if len(tail) != count * width:
            raise ApiError(f"{struct_type.__name__} claims {count} it did not send")
        setattr(head, flex.field, list(_array(flex.elem, count).from_buffer_copy(tail)))
    return head


# ── The surface derived from the enums ───────────────────────────────────────


class MethodSpec(NamedTuple):
    """One callable method, and the payload types its own name predicts."""

    name: str
    ns: int
    method: int
    args: type | None
    ret: type | None
    fields: tuple[str, ...]


def _positional_fields(args_type: type | None) -> tuple[str, ...]:
    """Return the arguments a caller may pass by position, in order."""
    if args_type is None:
        return ()
    declared = getattr(args_type, "_fields_", [])
    names = [name for name, *_ in declared if not name.startswith("_pad")]
    flex = fw_abi.FLEX.get(args_type)
    if flex is not None:
        names = [n for n in names if n != flex.count_field] + [flex.field]
    return tuple(names)


def _methods(stem: str, ns: int, method_enum: Any) -> dict[str, MethodSpec]:
    """Return one namespace's methods, keyed by the name they answer to."""
    specs: dict[str, MethodSpec] = {}
    for member in method_enum:
        if member.name.endswith("_COUNT"):
            continue
        payload_stem = member.name.lower()
        args = getattr(fw_abi, f"{payload_stem}_args", None)
        ret = getattr(fw_abi, f"{payload_stem}_ret", None)
        attr = member.name.removeprefix(f"RPC_{stem}_").lower()
        specs[attr] = MethodSpec(
            name=f"{stem.lower()}.{attr}",
            ns=ns,
            method=int(member),
            args=args,
            ret=ret,
            fields=_positional_fields(args),
        )
    return specs


def namespaces() -> dict[str, dict[str, MethodSpec]]:
    """Return every namespace that has methods, derived from the enums."""
    found: dict[str, dict[str, MethodSpec]] = {}
    for member in fw_abi.rpc_ns_t:
        if member.name.endswith("_COUNT"):
            continue
        stem = member.name.removeprefix("RPC_NS_")
        method_enum = getattr(fw_abi, f"rpc_{stem.lower()}_method_t", None)
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

    return pack(spec.args, values) if spec.args is not None else b""


def result(spec: MethodSpec, payload: bytes) -> Any:
    """Return what the reply carried, as the struct this method promises."""
    if spec.ret is None:
        return None
    return unpack(spec.ret, payload)


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
    return getattr(fw_abi, name)


def __dir__() -> list[str]:
    """Return this module's own names plus everything the ABI carries."""
    return sorted({*globals(), *vars(fw_abi)})
