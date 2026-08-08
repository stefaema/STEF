"""What this fixture's calls take, as any subsystem would hand it over.

Annotations are strings here, per `from __future__ import annotations`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Register(enum.IntEnum):
    """A register this fixture pretends to have."""

    GCONF = 0x00
    GSTAT = 0x01
    CHOPCONF = 0x6C


class Condition(enum.IntFlag):
    """A fault this fixture pretends to report."""

    OVERTEMP = 1 << 0
    SHORT_CIRCUIT = 1 << 1
    OPEN_LOAD = 1 << 2


@dataclass
class Op:
    """One register and the value to put in it."""

    reg: Register = Register.GCONF
    value: int = 0


@dataclass
class ReadArgs:
    """A device and the register to read from it."""

    idx: int = 0
    reg: Register = Register.GCONF


@dataclass
class WriteArgs:
    """A device, and a batch of registers to write to it."""

    idx: int = 0
    ops: list[Op] = field(default_factory=list)


@dataclass
class MoveArgs:
    """A run, as the fixture's driver would take it."""

    idx: int = 0
    forward: bool = True
    pulses: int = 0
    cruise_pps: int = 0


@dataclass
class ClearArgs:
    """Which faults to acknowledge."""

    idx: int = 0
    conditions: Condition = Condition.OVERTEMP


@dataclass
class SendArgs:
    """A datagram assembled by the caller."""

    idx: int = 0
    tx: bytes = b""


@dataclass
class Unrenderable:
    """A payload carrying something no parameter kind draws."""

    when: complex = 0j
