"""Messages between GuiModel and SubsystemWorker, and the channels that GuiModel publishes on.

Every field holds a value that `shared.diagnostics.as_json` can serialise. This lets
a worker run in a subprocess later without changes to the model.
"""

import enum
from dataclasses import dataclass
from typing import Any

from shared.diagnostics import SubsystemView, TestView

# ── Requests from the model to a worker ──────────────────────────────────────


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


# ── Events from a worker to the model ────────────────────────────────────────


class FailureKind(enum.Enum):
    """Why a request failed."""

    NOT_READY = "not_ready"
    STOP_UNCONFIRMED = "stop_unconfirmed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RequestFinished:
    """Sent when a request is finished. reply holds its return value. failure holds the reason if it failed."""

    subsystem_id: str
    request_id: int
    reply: Any = None
    failure: str | None = None
    failure_kind: FailureKind | None = None


@dataclass(frozen=True, slots=True)
class SubsystemChanged:
    """Sent when the link, readiness or facts change. It carries the whole subsystem view."""

    subsystem_view: SubsystemView
    link_changed: bool


@dataclass(frozen=True, slots=True)
class TestChanged:
    """Sent when a step finishes, a question opens or closes, or a stop is requested."""

    subsystem_id: str
    test_view: TestView


@dataclass(frozen=True, slots=True)
class TestEnded:
    """Sent when a test run ends."""

    subsystem_id: str
    test_view: TestView
    hazardous: bool


WorkerEvent = RequestFinished | SubsystemChanged | TestChanged | TestEnded


# ── Channels that the model publishes on ─────────────────────────────────────


class Channel(enum.Enum):
    """The kind of a published change. All subsystems use the same four channels."""

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
    """A change that the model published. subsystem_id and test_key identify what changed."""

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
