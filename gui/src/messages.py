"""The closed sets of messages between GuiModel and a SubsystemWorker, and the channels the browser hears.

Every field is a value `shared.diagnostics.as_json` serialises, so a worker can move
into a subprocess without changing the model.
"""

import enum
from dataclasses import dataclass
from typing import Any

from shared.diagnostics import SubsystemView, TestView

# ── Requests: the model asks a worker ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Connect:
    request_id: int
    target: Any


@dataclass(frozen=True, slots=True)
class Disconnect:
    request_id: int


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    request_id: int
    target: Any


@dataclass(frozen=True, slots=True)
class StartTest:
    request_id: int
    test_key: str
    form_values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnswerQuestion:
    request_id: int
    answer: Any


@dataclass(frozen=True, slots=True)
class RequestStop:
    request_id: int


@dataclass(frozen=True, slots=True)
class CallCommand:
    request_id: int
    command_key: str
    form_values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ListOptions:
    request_id: int
    item_key: str
    input_name: str


WorkerRequest = (
    Connect
    | Disconnect
    | ProbeTarget
    | StartTest
    | AnswerQuestion
    | RequestStop
    | CallCommand
    | ListOptions
)


# ── Events: a worker tells the model ─────────────────────────────────────────


class FailureKind(enum.Enum):
    """Why a request did not do what it asked."""

    NOT_READY = "not_ready"
    STOP_UNCONFIRMED = "stop_unconfirmed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RequestFinished:
    """One request is done. reply is what it returned; failure says why it did not."""

    subsystem_id: str
    request_id: int
    reply: Any = None
    failure: str | None = None
    failure_kind: FailureKind | None = None


@dataclass(frozen=True, slots=True)
class SubsystemChanged:
    """Something that changes what the whole board shows: the link, readiness, facts."""

    subsystem_view: SubsystemView
    link_changed: bool


@dataclass(frozen=True, slots=True)
class TestChanged:
    """One test moved: a step settled, a question opened or closed, a stop was asked."""

    subsystem_id: str
    test_view: TestView


@dataclass(frozen=True, slots=True)
class TestEnded:
    """One test's run is over, whatever its verdict."""

    subsystem_id: str
    test_view: TestView
    hazardous: bool


WorkerEvent = RequestFinished | SubsystemChanged | TestChanged | TestEnded


# ── Channels: the model tells the browser ────────────────────────────────────


class Channel(enum.Enum):
    """One kind of change the screen shows. Every subsystem shares the same four."""

    LOG = "log"
    LINK = "link"
    TEST_PROGRESS = "test_progress"
    FOCUS = "focus"


@dataclass(frozen=True, slots=True)
class LogLine:
    sequence: int
    time: float
    source: str
    level: str
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class Change:
    """One change the model published. subsystem_id and test_key say what changed."""

    channel: Channel
    subsystem_id: str | None = None
    test_key: str | None = None
    test_ended: bool = False
    log_line: LogLine | None = None


__all__ = [
    "AnswerQuestion",
    "CallCommand",
    "Change",
    "Channel",
    "Connect",
    "Disconnect",
    "FailureKind",
    "ListOptions",
    "LogLine",
    "ProbeTarget",
    "RequestFinished",
    "RequestStop",
    "StartTest",
    "SubsystemChanged",
    "TestChanged",
    "TestEnded",
    "WorkerEvent",
    "WorkerRequest",
]
