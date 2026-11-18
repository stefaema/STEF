"""Runs every call to one subsystem on one thread.

The worker serves one request at a time, so two requests never use the port at once.
A test runs on a separate thread that the worker owns. This lets the worker pass on
an answer or a stop while the test runs.
"""

import dataclasses
import queue
import threading
from collections.abc import Callable
from typing import Any

from gui.src.messages import (
    AnswerQuestion,
    CallCommand,
    Connect,
    Disconnect,
    FailureKind,
    ListOptions,
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
from shared import logs
from shared.diagnostics import (
    Diagnosable,
    Needs,
    StopUnconfirmed,
    SubsystemView,
    TestView,
)
from shared.diagnostics.views import subsystem_view, view_of_test
from shared.subsystem import (
    Level,
    Linked,
    LinkState,
    NotReady,
    Result,
    answered,
    coerced,
)

# Seconds between link checks, for changes that were not announced.
LINK_CHECK_INTERVAL_S = 1.0
# Seconds that close() waits for each thread to finish.
CLOSE_PATIENCE_S = 30.0

log = logs.as_component("gui")


def facts_or_warning(subsystem: Diagnosable) -> Result | None:
    """Return the subsystem's facts, or a warning Result if reading them raised."""
    try:
        return subsystem.facts()
    except Exception as exc:
        return Result(level=Level.WARN, summary=f"{type(exc).__name__}: {exc}")


class SubsystemWorker:
    def __init__(
        self, subsystem: Diagnosable, send_event: Callable[[WorkerEvent], None]
    ) -> None:
        """Serve requests for subsystem and pass every event to send_event."""
        self.subsystem = subsystem
        self._send_event = send_event
        self._requests: queue.Queue[WorkerRequest | None] = queue.Queue()
        self._closing = threading.Event()
        self._request_thread: threading.Thread | None = None
        self._link_check_thread: threading.Thread | None = None
        self._test_thread: threading.Thread | None = None
        self._facts: Result | None = None
        self._link_check_lock = threading.Lock()
        self._last_link_seen = self._link_now()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if isinstance(self.subsystem, Linked):
            self.subsystem.watch_link(self._check_link)
        name = self.subsystem.id
        self._request_thread = threading.Thread(
            target=self._serve_requests, name=f"worker:{name}", daemon=True
        )
        self._link_check_thread = threading.Thread(
            target=self._check_link_every_interval, name=f"link:{name}", daemon=True
        )
        self._request_thread.start()
        self._link_check_thread.start()

    def submit(self, request: WorkerRequest) -> None:
        self._requests.put(request)

    def close(self) -> None:
        """Cancel a running test and wait for it, stop the threads, then disconnect the subsystem."""
        self._closing.set()
        self.subsystem.cancel()
        test_thread = self._test_thread
        if test_thread is not None:
            test_thread.join(CLOSE_PATIENCE_S)
        self._requests.put(None)
        for thread in (self._request_thread, self._link_check_thread):
            if thread is not None:
                thread.join(CLOSE_PATIENCE_S)
        if isinstance(self.subsystem, Linked):
            try:
                self.subsystem.disconnect()
            except Exception as exc:
                log.error(
                    "{}: disconnecting on close failed: {}", self.subsystem.id, exc
                )

    # ── Views ────────────────────────────────────────────────────────────────

    def current_view(self) -> SubsystemView:
        """Return the current subsystem view, with the cached facts."""
        unread = subsystem_view(self.subsystem, operator=True, read_facts=False)
        return dataclasses.replace(unread, facts=self._facts)

    def _test_view(self, test_key: str) -> TestView:
        return view_of_test(self.subsystem, self.subsystem.test(test_key), True)

    # ── Requests ─────────────────────────────────────────────────────────────

    def _serve_requests(self) -> None:
        while True:
            request = self._requests.get()
            if request is None:
                return
            self._send_event(self._served(request))

    def _served(self, request: WorkerRequest) -> RequestFinished:
        subsystem_id = self.subsystem.id
        try:
            reply = self._reply_to(request)
        except NotReady as exc:
            return RequestFinished(
                subsystem_id, request.request_id, None, str(exc), FailureKind.NOT_READY
            )
        except StopUnconfirmed as exc:
            return RequestFinished(
                subsystem_id,
                request.request_id,
                None,
                str(exc),
                FailureKind.STOP_UNCONFIRMED,
            )
        except Exception as exc:
            return RequestFinished(
                subsystem_id,
                request.request_id,
                None,
                f"{type(exc).__name__}: {exc}",
                FailureKind.ERROR,
            )
        return RequestFinished(subsystem_id, request.request_id, reply)

    def _reply_to(self, request: WorkerRequest) -> Any:
        subsystem = self.subsystem
        match request:
            case Connect(target=target):
                linked = self._linked()
                linked.connect(self._target_value(linked, target))
                return None
            case Disconnect():
                self._linked().disconnect()
                return None
            case ProbeTarget(target=target):
                linked = self._linked()
                return answered(linked.probe(self._target_value(linked, target)))
            case StartTest(test_key=test_key, form_values=form_values):
                self._start_test(test_key, form_values)
                return None
            case AnswerQuestion(answer=answer):
                subsystem.answer(answer)
                return None
            case RequestStop():
                running = subsystem.running()
                deferred = subsystem.request_stop()
                if running is not None:
                    self._send_test_changed(running.test.key)
                return deferred
            case CallCommand(command_key=command_key, form_values=form_values):
                reply = subsystem.run_command(command_key, form_values)
                self._refresh_facts()
                self._send_event(SubsystemChanged(self.current_view(), False))
                return reply
            case ListOptions(item_key=item_key, input_name=input_name):
                return list(subsystem.options(item_key, input_name))

    def _target_value(self, linked: Linked[Any], submitted: Any) -> Any:
        """Convert the submitted form value to the type that the link's target input declares."""
        return coerced(type(linked).target, submitted, linked)

    def _linked(self) -> Linked[Any]:
        if not isinstance(self.subsystem, Linked):
            raise NotReady(f"{self.subsystem.id} has no link")
        return self.subsystem

    # ── Running a test ───────────────────────────────────────────────────────

    def _start_test(self, test_key: str, form_values: dict[str, Any]) -> None:
        """Start the test on its own thread. Return once the run is registered, or raise the error that prevented it."""
        registered = threading.Event()
        refused: list[Exception] = []

        def run_test_to_its_end() -> None:
            try:
                self.subsystem.run_test(
                    test_key,
                    form_values,
                    lambda _record: self._send_test_changed(test_key),
                    operator=True,
                    on_started=registered.set,
                )
            except Exception as exc:
                if not registered.is_set():
                    refused.append(exc)
                else:
                    log.error("{}.{}: {}", self.subsystem.id, test_key, exc)
            finally:
                was_registered = registered.is_set()
                registered.set()
                if was_registered:
                    self._test_ended(test_key)

        self._test_thread = threading.Thread(
            target=run_test_to_its_end,
            name=f"test:{self.subsystem.id}.{test_key}",
            daemon=True,
        )
        self._test_thread.start()
        registered.wait()
        if refused:
            raise refused[0]
        self._send_test_changed(test_key)

    def _send_test_changed(self, test_key: str) -> None:
        self._send_event(TestChanged(self.subsystem.id, self._test_view(test_key)))

    def _test_ended(self, test_key: str) -> None:
        self._refresh_facts()
        test = self.subsystem.test(test_key)
        self._send_event(
            TestEnded(self.subsystem.id, self._test_view(test_key), test.hazardous())
        )
        self._send_event(SubsystemChanged(self.current_view(), False))

    # ── The link ─────────────────────────────────────────────────────────────

    def _link_now(self) -> tuple[LinkState, str | None]:
        if not isinstance(self.subsystem, Linked):
            return LinkState.DOWN, None
        return self.subsystem.link_state(), self.subsystem.link_reason()

    def _check_link(self) -> None:
        """Send the subsystem view if the link state changed since the last check. Can be called from any thread."""
        with self._link_check_lock:
            link_now = self._link_now()
            if link_now == self._last_link_seen:
                return
            self._last_link_seen = link_now
            state, _ = link_now
            self._facts = (
                facts_or_warning(self.subsystem) if state is LinkState.UP else None
            )
        if state in (LinkState.DOWN, LinkState.ERROR):
            self._cancel_test_that_lost_its_link()
        self._send_event(SubsystemChanged(self.current_view(), True))

    def _cancel_test_that_lost_its_link(self) -> None:
        """Cancel a running test that needs the link, because it can't reach the hardware without it."""
        running = self.subsystem.running()
        if running is None or running.test.needs is Needs.DOWN:
            return
        log.error("{}: the link was lost while it ran. Cancelling it", running.name)
        self.subsystem.request_stop()

    def _check_link_every_interval(self) -> None:
        while not self._closing.wait(LINK_CHECK_INTERVAL_S):
            self._check_link()

    def _refresh_facts(self) -> None:
        with self._link_check_lock:
            state, _ = self._link_now()
            self._facts = (
                facts_or_warning(self.subsystem) if state is LinkState.UP else None
            )


__all__ = ["LINK_CHECK_INTERVAL_S", "SubsystemWorker", "facts_or_warning"]
