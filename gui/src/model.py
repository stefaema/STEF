"""Everything the GUI knows and everything it can do, in one object the routes only call.

GuiModel owns the machine and its focus, one SubsystemWorker per subsystem, what
each board last looked like, and the log. Routes call its methods and render what
it holds. Every change goes out to subscribers as a Change on one of four channels.
"""

import dataclasses
import itertools
import threading
import time
from collections import deque
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from gui.src.i18n import gettext
from gui.src.messages import (
    AnswerQuestion,
    CallCommand,
    Change,
    Channel,
    Connect,
    Disconnect,
    FailureKind,
    ListOptions,
    LogLine,
    ProbeTarget,
    RequestFinished,
    RequestStop,
    StartTest,
    SubsystemChanged,
    TestChanged,
    TestEnded,
    WorkerEvent,
    WorkerRequest,
)
from gui.src.worker import SubsystemWorker
from machine import Activity, Busy, Machine
from shared import logs
from shared.diagnostics import Diagnosable, SubsystemView, TestView
from shared.subsystem import Level, LinkState, Readiness, Result, blocked

# How many log lines a browser that connects late is shown.
LOG_BACKLOG = 200
# How long an action waits for its worker before telling the operator it never answered.
REPLY_TIMEOUT_S = 120.0

# What a logged level is called on a screen, which has three weights and not six.
SCREEN_LEVEL = {
    "TRACE": Level.OK,
    "DEBUG": Level.OK,
    "INFO": Level.OK,
    "SUCCESS": Level.OK,
    "WARNING": Level.WARN,
    "ERROR": Level.ERROR,
    "CRITICAL": Level.ERROR,
}


class Refused(Exception):
    """An action the model would not do, or that failed, as one sentence for the operator."""


@dataclass(frozen=True, slots=True)
class StopAlarm:
    """No stop reached the hardware, so nobody knows its state. Shown until acknowledged."""

    message: str
    hazardous: bool


@dataclass(slots=True)
class SubsystemState:
    view: SubsystemView
    stop_alarm: StopAlarm | None = None


@dataclass(slots=True)
class PendingRequest:
    done: threading.Event = dataclasses.field(default_factory=threading.Event)
    finished: RequestFinished | None = None


def with_test(view: SubsystemView, test_view: TestView) -> SubsystemView:
    """Return view with one test replaced by test_view, and what is running updated."""
    tests = tuple(test_view if one.key == test_view.key else one for one in view.tests)
    running = view.running
    if test_view.last is not None and test_view.last.running:
        running = test_view.key
    elif running == test_view.key:
        running = None
    return dataclasses.replace(view, tests=tests, running=running)


class GuiModel:
    def __init__(self, roster: tuple[str, ...] | None = None) -> None:
        """Hold the subsystems roster names, unassembled until start()."""
        self.machine = Machine(roster)
        self._workers: dict[str, SubsystemWorker] = {}
        self._states: dict[str, SubsystemState] = {}
        self._option_lists: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self._log_lines: deque[LogLine] = deque(maxlen=LOG_BACKLOG)
        self._log_sequence = itertools.count(1)
        self._listeners: list[Callable[[Change], None]] = []
        self._pending: dict[int, PendingRequest] = {}
        self._request_ids = itertools.count(1)
        self._lock = threading.Lock()
        self._log_sink_id: int | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Assemble the subsystems, start one worker each, and start hearing the log."""
        self._log_sink_id = logs.to(self._record_logged)
        self.machine.assemble()
        for subsystem_id, subsystem in self.machine.subsystems.items():
            if not isinstance(subsystem, Diagnosable):
                continue
            worker = SubsystemWorker(subsystem, self._apply)
            self._workers[subsystem_id] = worker
            self._states[subsystem_id] = SubsystemState(worker.current_view())
            worker.start()
        self.say("gui", Level.OK, "gui", gettext("Backend ready"))

    def close(self) -> None:
        """Let running tests end, stop and disconnect every subsystem, then stop hearing the log."""
        for subsystem_id, worker in self._workers.items():
            self.say(subsystem_id, Level.WARN, "command", "close()")
            worker.close()
        self.machine.unfocus()
        if self._log_sink_id is not None:
            logs.logger.remove(self._log_sink_id)
            self._log_sink_id = None

    # ── What it holds ────────────────────────────────────────────────────────

    @property
    def roster(self) -> tuple[str, ...]:
        return self.machine.roster

    def has_subsystem(self, subsystem_id: str) -> bool:
        return subsystem_id in self._states

    def first_subsystem_id(self) -> str | None:
        return next((one for one in self.roster if one in self._states), None)

    def subsystem_view(self, subsystem_id: str) -> SubsystemView:
        """Return the board as last seen. Raises KeyError for a subsystem that is not served."""
        with self._lock:
            return self._states[subsystem_id].view

    def test_view(self, subsystem_id: str, test_key: str) -> TestView:
        found = next(
            (
                one
                for one in self.subsystem_view(subsystem_id).tests
                if one.key == test_key
            ),
            None,
        )
        if found is None:
            raise KeyError(f"{subsystem_id} declares no test {test_key!r}")
        return found

    def stop_alarm(self, subsystem_id: str) -> StopAlarm | None:
        with self._lock:
            return self._states[subsystem_id].stop_alarm

    def link_is_up(self, subsystem_id: str) -> bool:
        link = self.subsystem_view(subsystem_id).link
        return link is not None and link.state is LinkState.UP

    @property
    def focus(self) -> tuple[Activity | None, str | None]:
        """Return what the focus is held for, and by what, both None while idle."""
        return self.machine.activity, self.machine.focus_holder

    def log_backlog(self) -> list[LogLine]:
        with self._lock:
            return list(self._log_lines)

    def cached_options(
        self, subsystem_id: str, item_key: str, input_name: str
    ) -> list[dict[str, Any]] | None:
        with self._lock:
            return self._option_lists.get((subsystem_id, item_key, input_name))

    # ── Who hears about changes ──────────────────────────────────────────────

    def subscribe(self, listener: Callable[[Change], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[Change], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    # ── What it can do ───────────────────────────────────────────────────────

    def probe_target(self, subsystem_id: str, target: Any) -> Readiness:
        """Ask whether target can be connected to. target is the value the form submitted."""
        finished = self._ask_worker(
            subsystem_id, lambda request_id: ProbeTarget(request_id, target)
        )
        if finished.failure is not None:
            return blocked(finished.failure)
        return finished.reply

    def connect(self, subsystem_id: str, target: Any) -> None:
        with self._focused(Activity.BENCHING, f"{subsystem_id}.connect"):
            self.say(subsystem_id, Level.OK, "command", f"connect({target!r})")
            self._reply_or_refuse(
                subsystem_id,
                self._ask_worker(
                    subsystem_id, lambda request_id: Connect(request_id, target)
                ),
            )
        self.say(subsystem_id, Level.OK, "result", gettext("Connected"))

    def disconnect(self, subsystem_id: str) -> None:
        self.say(subsystem_id, Level.OK, "command", "disconnect()")
        self._reply_or_refuse(subsystem_id, self._ask_worker(subsystem_id, Disconnect))
        self.say(subsystem_id, Level.OK, "result", gettext("Disconnected"))

    def start_test(
        self, subsystem_id: str, test_key: str, form_values: dict[str, Any]
    ) -> None:
        """Start one test. The focus stays held until the test ends."""
        holder = f"{subsystem_id}.{test_key}"
        self._focus_on(Activity.BENCHING, holder)
        self.say(subsystem_id, Level.OK, "command", f"{test_key}({shown(form_values)})")
        try:
            self._reply_or_refuse(
                subsystem_id,
                self._ask_worker(
                    subsystem_id,
                    lambda request_id: StartTest(request_id, test_key, form_values),
                ),
            )
        except Refused:
            self._unfocus(holder)
            raise

    def answer_question(self, subsystem_id: str, answer: Any) -> None:
        self._reply_or_refuse(
            subsystem_id,
            self._ask_worker(
                subsystem_id, lambda request_id: AnswerQuestion(request_id, answer)
            ),
        )

    def request_stop(self, subsystem_id: str) -> bool:
        """Ask for a stop. Return True when it waits for a running test's end step."""
        self.say(subsystem_id, Level.WARN, "command", "stop()")
        finished = self._ask_worker(subsystem_id, RequestStop)
        if finished.failure_kind is FailureKind.STOP_UNCONFIRMED:
            self._raise_stop_alarm(
                subsystem_id, finished.failure or "", hazardous=False
            )
        deferred = bool(self._reply_or_refuse(subsystem_id, finished))
        if deferred:
            self.say(
                subsystem_id,
                Level.WARN,
                "result",
                gettext("Stopping once the end step is done"),
            )
        else:
            self._clear_stop_alarm(subsystem_id)
            self.say(subsystem_id, Level.OK, "result", gettext("Stopped"))
        return deferred

    def call_command(
        self, subsystem_id: str, command_key: str, form_values: dict[str, Any]
    ) -> Result:
        with self._focused(Activity.BENCHING, f"{subsystem_id}.{command_key}"):
            self.say(
                subsystem_id,
                Level.OK,
                "command",
                f"{command_key}({shown(form_values)})",
            )
            reply: Result = self._reply_or_refuse(
                subsystem_id,
                self._ask_worker(
                    subsystem_id,
                    lambda request_id: CallCommand(
                        request_id, command_key, form_values
                    ),
                ),
            )
        self.say(subsystem_id, reply.level, "result", reply.summary)
        return reply

    def options(
        self, subsystem_id: str, item_key: str, input_name: str, refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Return an option list that only exists at runtime, asking the worker unless cached."""
        if not refresh:
            cached = self.cached_options(subsystem_id, item_key, input_name)
            if cached is not None:
                return cached
        finished = self._ask_worker(
            subsystem_id,
            lambda request_id: ListOptions(request_id, item_key, input_name),
        )
        if finished.failure is not None:
            raise KeyError(finished.failure)
        listed: list[dict[str, Any]] = list(finished.reply)
        with self._lock:
            self._option_lists[(subsystem_id, item_key, input_name)] = listed
        return listed

    def acknowledge_stop_alarm(self, subsystem_id: str) -> None:
        self.say(subsystem_id, Level.WARN, "command", gettext("alarm acknowledged"))
        self._clear_stop_alarm(subsystem_id)

    # ── The log ──────────────────────────────────────────────────────────────

    def say(self, source: str, level: Level, kind: str, text: str) -> None:
        """Add one line to the screen's log."""
        line = LogLine(
            next(self._log_sequence), time.time(), source, level.value, kind, text
        )
        with self._lock:
            self._log_lines.append(line)
        self._publish(Change(Channel.LOG, log_line=line))

    def _record_logged(self, message: Any) -> None:
        """Put one logged record on the screen's log, as shared.logs hands it to a sink."""
        record = getattr(message, "record", None)
        if record is None:
            self.say("stef", Level.OK, "log", str(message).rstrip())
            return
        self.say(
            str(record["extra"].get("component", "stef")),
            SCREEN_LEVEL.get(record["level"].name, Level.OK),
            "log",
            str(record["message"]),
        )

    # ── Talking to workers ───────────────────────────────────────────────────

    def _ask_worker(
        self, subsystem_id: str, make_request: Callable[[int], WorkerRequest]
    ) -> RequestFinished:
        worker = self._workers.get(subsystem_id)
        if worker is None:
            raise KeyError(f"no subsystem {subsystem_id!r}")
        request_id = next(self._request_ids)
        pending = PendingRequest()
        with self._lock:
            self._pending[request_id] = pending
        worker.submit(make_request(request_id))
        if not pending.done.wait(REPLY_TIMEOUT_S):
            with self._lock:
                self._pending.pop(request_id, None)
            raise Refused(
                gettext("%(subsystem)s did not answer within %(seconds).0f s")
                % {"subsystem": subsystem_id, "seconds": REPLY_TIMEOUT_S}
            )
        assert pending.finished is not None
        return pending.finished

    def _reply_or_refuse(self, subsystem_id: str, finished: RequestFinished) -> Any:
        if finished.failure is None:
            return finished.reply
        level = (
            Level.WARN
            if finished.failure_kind is FailureKind.NOT_READY
            else Level.ERROR
        )
        self.say(subsystem_id, level, "result", finished.failure)
        raise Refused(finished.failure)

    def _apply(self, event: WorkerEvent) -> None:
        """Take in one event from a worker, on the worker's thread, and publish what changed."""
        match event:
            case RequestFinished(request_id=request_id):
                with self._lock:
                    pending = self._pending.pop(request_id, None)
                if pending is not None:
                    pending.finished = event
                    pending.done.set()
            case SubsystemChanged(subsystem_view=view, link_changed=link_changed):
                with self._lock:
                    self._states[view.id].view = view
                    if link_changed:
                        for cached in [
                            k for k in self._option_lists if k[0] == view.id
                        ]:
                            del self._option_lists[cached]
                self._publish(Change(Channel.LINK, subsystem_id=view.id))
            case TestChanged(subsystem_id=subsystem_id, test_view=test_view):
                self._replace_test(subsystem_id, test_view)
                self._publish(
                    Change(Channel.TEST_PROGRESS, subsystem_id, test_view.key)
                )
            case TestEnded(
                subsystem_id=subsystem_id, test_view=test_view, hazardous=hazardous
            ):
                self._replace_test(subsystem_id, test_view)
                self._unfocus(f"{subsystem_id}.{test_view.key}")
                last = test_view.last
                if last is not None and last.stop_unconfirmed:
                    self._raise_stop_alarm(
                        subsystem_id, last.stop_unconfirmed, hazardous
                    )
                self._publish(
                    Change(Channel.TEST_PROGRESS, subsystem_id, test_view.key, True)
                )

    def _replace_test(self, subsystem_id: str, test_view: TestView) -> None:
        with self._lock:
            state = self._states[subsystem_id]
            state.view = with_test(state.view, test_view)

    # ── The focus and the alarm ──────────────────────────────────────────────

    def _focus_on(self, activity: Activity, holder: str) -> None:
        try:
            self.machine.focus_on(activity, holder)
        except Busy as busy:
            raise Refused(
                gettext("The machine is busy with %(holder)s") % {"holder": busy.holder}
            ) from busy
        self._publish(Change(Channel.FOCUS))

    def _unfocus(self, holder: str) -> None:
        if self.machine.focus_holder != holder:
            return
        self.machine.unfocus()
        self._publish(Change(Channel.FOCUS))

    @contextmanager
    def _focused(self, activity: Activity, holder: str) -> Generator[None]:
        self._focus_on(activity, holder)
        try:
            yield
        finally:
            self._unfocus(holder)

    def _raise_stop_alarm(
        self, subsystem_id: str, message: str, hazardous: bool
    ) -> None:
        with self._lock:
            self._states[subsystem_id].stop_alarm = StopAlarm(message, hazardous)
        self.say(subsystem_id, Level.ERROR, "alarm", message)
        self._publish(Change(Channel.LINK, subsystem_id=subsystem_id))

    def _clear_stop_alarm(self, subsystem_id: str) -> None:
        with self._lock:
            state = self._states[subsystem_id]
            had_alarm = state.stop_alarm is not None
            state.stop_alarm = None
        if had_alarm:
            self._publish(Change(Channel.LINK, subsystem_id=subsystem_id))

    def _publish(self, change: Change) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(change)
            except Exception:
                pass


def shown(values: dict[str, Any]) -> str:
    """Return submitted values on one line, as an echoed call shows them."""
    return ", ".join(f"{name}={value!r}" for name, value in values.items())


__all__ = ["GuiModel", "Refused", "StopAlarm", "SubsystemState", "with_test"]
