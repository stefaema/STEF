"""The middle ground between a Python type and a drawn control.

A type says what a value is. A control says how it is picked: a select, a
checkbox, a hex field. A parameter names which of the six a value gets, and
carries every conversion that choice implies in both directions.
"""

import enum
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, NamedTuple, Required, TypedDict, cast


class Option(NamedTuple):
    """One choice whose sent value and read label are not the same string."""

    value: Any
    label: str


# Either a fixed sequence, an enum class, or a zero-argument callable that returns a sequence.
Options = Sequence[Any] | type[enum.Enum] | Callable[[], Sequence[Any]]


class ChoiceParam(TypedDict, total=False):
    """A pick-one: over a fixed sequence, an enum class, or a live list."""

    name: Required[str]
    kind: Required[Literal["choice"]]
    options: Required[Options]
    hint: str | None


class BooleanParam(TypedDict, total=False):
    """An on-or-off."""

    name: Required[str]
    kind: Required[Literal["boolean"]]
    hint: str | None


class IntegerParam(TypedDict, total=False):
    """A number, with whatever bounds and unit the subsystem knows."""

    name: Required[str]
    kind: Required[Literal["integer"]]
    unit: str | None
    min: int | None
    max: int | None
    hint: str | None


class BitmaskParam(TypedDict, total=False):
    """A pick-many, over the members of a flag set."""

    name: Required[str]
    kind: Required[Literal["bitmask"]]
    options: Required[Options]
    hint: str | None


class RawBytesParam(TypedDict, total=False):
    """Bytes a caller assembles themselves."""

    name: Required[str]
    kind: Required[Literal["raw_bytes"]]
    hint: str | None


class GroupParam(TypedDict, total=False):
    """A repeating row of controls, one column per parameter given."""

    name: Required[str]
    kind: Required[Literal["group"]]
    columns: Required[tuple["ParamSpec", ...]]
    hint: str | None


ParamSpec = (
    ChoiceParam
    | BooleanParam
    | IntegerParam
    | BitmaskParam
    | RawBytesParam
    | GroupParam
)


# ── Declaring one ────────────────────────────────────────────────────────────


def choice(name: str, options: Options, *, hint: str | None = None) -> ChoiceParam:
    """Return a pick-one control over a fixed sequence or a zero-argument callable."""
    return {"name": name, "kind": "choice", "options": options, "hint": hint}


def boolean(name: str, *, hint: str | None = None) -> BooleanParam:
    """Return an on-or-off control."""
    return {"name": name, "kind": "boolean", "hint": hint}


def integer(
    name: str,
    *,
    unit: str | None = None,
    min: int | None = None,
    max: int | None = None,
    hint: str | None = None,
) -> IntegerParam:
    """Return a number control, with whatever bounds and unit the subsystem knows."""
    return {
        "name": name,
        "kind": "integer",
        "unit": unit,
        "min": min,
        "max": max,
        "hint": hint,
    }


def bitmask(name: str, options: Options, *, hint: str | None = None) -> BitmaskParam:
    """Return a pick-many control over the members of a flag set."""
    return {"name": name, "kind": "bitmask", "options": options, "hint": hint}


def raw_bytes(name: str, *, hint: str | None = None) -> RawBytesParam:
    """Return a control for bytes a caller assembles themselves."""
    return {"name": name, "kind": "raw_bytes", "hint": hint}


def group(
    name: str, *, columns: Sequence[ParamSpec], hint: str | None = None
) -> GroupParam:
    """Return a repeating row of controls, one column per parameter given."""
    return {"name": name, "kind": "group", "columns": tuple(columns), "hint": hint}


# ── What a decorator refuses at import ───────────────────────────────────────


class ParamError(TypeError):
    """A parameter naming a kind, or carrying a key, that no control renders."""


_ALLOWED: dict[str, set[str]] = {
    "choice": {"name", "kind", "options", "hint"},
    "boolean": {"name", "kind", "hint"},
    "integer": {"name", "kind", "unit", "min", "max", "hint"},
    "bitmask": {"name", "kind", "options", "hint"},
    "raw_bytes": {"name", "kind", "hint"},
    "group": {"name", "kind", "columns", "hint"},
}

_NEEDED: dict[str, set[str]] = {
    "choice": {"options"},
    "bitmask": {"options"},
    "group": {"columns"},
}


def validated(params: Sequence[ParamSpec]) -> tuple[ParamSpec, ...]:
    """Return the parameters, refusing any hand-written dict no control could draw."""
    for item in params:
        _refuse_unrenderable(item)
    return tuple(params)


def _refuse_unrenderable(item: ParamSpec) -> None:
    """Raise on one parameter whose kind or keys name nothing that draws."""
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise ParamError(f"a parameter declares no name: {item!r}")

    kind = item.get("kind")
    if kind not in _ALLOWED:
        raise ParamError(f"{name!r} is of kind {kind!r}, which no control renders")

    unknown = sorted(set(item) - _ALLOWED[kind])
    if unknown:
        raise ParamError(f"{name!r} is a {kind} and carries no {', '.join(unknown)}")

    missing = sorted(key for key in _NEEDED.get(kind, set()) if item.get(key) is None)
    if missing:
        raise ParamError(f"{name!r} is a {kind} and needs {', '.join(missing)}")

    for column in item.get("columns", ()):  # type: ignore[typeddict-item]
        _refuse_unrenderable(column)


# ── The options a choice or a bitmask offers ─────────────────────────────────


def _fetcher(item: ParamSpec) -> Callable[[], Sequence[Any]] | None:
    """Return the callable the options must come from, or None where they are fixed."""
    options = item.get("options")
    if callable(options) and not isinstance(options, type):
        return cast(Callable[[], Sequence[Any]], options)
    return None


def needs_fetch(item: ParamSpec) -> bool:
    """Whether the options are unknown until called for (therefore, options is a callable)."""
    return _fetcher(item) is not None


def options_name(item: ParamSpec) -> str | None:
    """Return the name the options are fetched by, or None where nothing is called."""
    fetch = _fetcher(item)
    return fetch.__name__ if fetch else None


def current_options(item: ParamSpec) -> tuple[Any, ...]:
    """Return the options as they stand now, calling for them if that is needed."""
    fetch = _fetcher(item)
    if fetch is not None:
        return tuple(fetch())
    options = item.get("options")
    if options is None:
        return ()
    return tuple(cast(Iterable[Any], options))


def labelled(value: Any) -> dict[str, Any]:
    """Return one option as the value a call takes and the label an operator reads.

    An `Option` says the two differ. Everything else labels itself, an enum
    member by its name and anything else by how it prints.
    """
    if isinstance(value, Option):
        return {"value": value.value, "label": value.label}
    if isinstance(value, enum.Enum):
        return {"value": value.value, "label": value.name}
    if isinstance(value, (tuple, list)):
        raise ParamError(
            f"option {value!r} is a bare sequence; use Option(value, label)"
        )
    return {"value": value, "label": str(value)}


def choices(item: ParamSpec) -> tuple[dict[str, Any], ...]:
    """Return every option as it stands now, each labelled."""
    return tuple(labelled(value) for value in current_options(item))


# ── What a blank form holds ──────────────────────────────────────────────────


def initial(item: ParamSpec) -> Any:
    """Return what a control holds before anyone touches it."""
    if item["kind"] == "boolean":
        return False
    if item["kind"] == "group":
        return []
    if item["kind"] == "raw_bytes":
        return ""
    if item["kind"] == "choice":
        picks = choices(item)
        return picks[0]["value"] if picks else None
    return item.get("min") or 0


# ── A filled form, as the Python the call takes ──────────────────────────────


def arguments(params: Sequence[ParamSpec], values: Mapping[str, Any]) -> dict[str, Any]:
    """Return submitted values as the Python each parameter promises."""
    taken = {}
    for item in params:
        if item["name"] not in values:
            continue
        taken[item["name"]] = typed(item, values[item["name"]])
    return taken


def typed(item: ParamSpec, value: Any) -> Any:
    """Return one submitted value as the type its kind promises.

    A form arrives over a transport with a thinner vocabulary than Python's, so
    a number may be text and bytes are certainly text.
    """
    if item["kind"] == "boolean":
        return bool(value)
    if item["kind"] in ("integer", "bitmask"):
        return int(value or 0)
    if item["kind"] == "raw_bytes":
        return as_bytes(value)
    if item["kind"] == "group":
        return [
            {c["name"]: typed(c, row.get(c["name"], 0)) for c in item["columns"]}
            for row in value or []
        ]
    if (
        item["kind"] == "choice"
        and isinstance(value, str)
        and value.lstrip("-").isdigit()
    ):
        return int(value)
    return value


def as_bytes(value: Any) -> bytes:
    """Return hex an operator typed as the bytes it stands for, refusing what is not.

    Spacing and an `0x` are how a datasheet writes it. An odd digit count pads on
    the left, since the digits are a number and padding the right scales it.
    """
    if isinstance(value, bytes):
        return value
    text = "".join(str(value or "").split()).removeprefix("0x")
    if not text:
        return b""
    try:
        return bytes.fromhex(text if len(text) % 2 == 0 else "0" + text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not hexadecimal") from exc
