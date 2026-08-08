"""The six kinds of control a form is built from."""

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


class Kind(enum.Enum):
    """What a parameter renders as."""

    CHOICE = "choice"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    BITMASK = "bitmask"
    RAW_BYTES = "raw_bytes"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class Param:
    """One field of a form, and everything the GUI needs to draw it.

    Every constructor below names its field first, so a Param is self-describing
    wherever it turns up and `params` can be a sequence rather than a dict.
    """

    name: str
    kind: Kind
    options: Any = None  # a sequence, an enum class, or a zero-argument callable
    columns: tuple["Param", ...] = ()
    unit: str | None = None
    min: int | None = None
    max: int | None = None
    hint: str | None = None

    @property
    def live(self) -> bool:
        """Whether the options are fetched on each render. A class never is."""
        return callable(self.options) and not isinstance(self.options, type)

    @property
    def catalog(self) -> str | None:
        """Return the name a live list is fetched by, or None when it ships inline."""
        return self.options.__name__ if self.live else None

    def resolved(self) -> Sequence[Any]:
        """Return the options as they stand now, running a live list if that is one."""
        if self.options is None:
            return ()
        return self.options() if self.live else list(self.options)


def choice(name: str, options: Any, *, hint: str | None = None) -> Param:
    """Return a pick-one control over a fixed sequence or a zero-argument callable."""
    return Param(name=name, kind=Kind.CHOICE, options=options, hint=hint)


def boolean(name: str, *, hint: str | None = None) -> Param:
    """Return an on-or-off control."""
    return Param(name=name, kind=Kind.BOOLEAN, hint=hint)


def integer(
    name: str,
    *,
    unit: str | None = None,
    min: int | None = None,
    max: int | None = None,
    hint: str | None = None,
) -> Param:
    """Return a number control, with whatever bounds and unit the subsystem knows."""
    return Param(name=name, kind=Kind.INTEGER, unit=unit, min=min, max=max, hint=hint)


def bitmask(name: str, options: Any, *, hint: str | None = None) -> Param:
    """Return a pick-many control over the members of a flag set."""
    return Param(name=name, kind=Kind.BITMASK, options=options, hint=hint)


def raw_bytes(name: str, *, hint: str | None = None) -> Param:
    """Return a control for bytes a caller assembles themselves."""
    return Param(name=name, kind=Kind.RAW_BYTES, hint=hint)


def group(name: str, *, columns: Sequence[Param], hint: str | None = None) -> Param:
    """Return a repeating row of controls, one column per parameter given."""
    return Param(name=name, kind=Kind.GROUP, columns=tuple(columns), hint=hint)
