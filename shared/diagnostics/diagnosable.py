import threading
import time
from collections.abc import Mapping
from types import ModuleType
from typing import TYPE_CHECKING, Any, ClassVar

from shared.diagnostics import run_log
from shared.diagnostics.commands import Command
from shared.diagnostics.records import Needs
from shared.diagnostics.runner import Report, Run
from shared.diagnostics.steps import Test
from shared.subsystem import (
    READY,
    DeclarationError,
    Input,
    Level,
    LinkState,
    NotReady,
    Readiness,
    Result,
    Subsystem,
    answered,
    blocked,
    coerced_values,
    input_named,
    labelled_options,
)

if TYPE_CHECKING:
    from shared.diagnostics.views import RunView, SubsystemView

LINK_KEY = "link"


class Diagnosable(Subsystem):
    tests: ClassVar[tuple[type[Test[Any]], ...]] = ()
    commands: ClassVar[tuple[Command, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        keys = [one.key for one in cls.tests] + [one.key for one in cls.commands]
        repeated = sorted({one for one in keys if keys.count(one) > 1})
        if repeated:
            raise DeclarationError(
                f"{cls.__name__} declares {', '.join(repeated)} more than once"
            )
        if LINK_KEY in keys:
            raise DeclarationError(f"{LINK_KEY!r} is reserved for the link")

    def __init__(self, package: ModuleType) -> None:
        super().__init__(package)
        self._run_lock = threading.Lock()
        self._running: Run | None = None
        self._runs: dict[str, Run] = {}
        self._replies: dict[str, Result] = {}

    # ── What is declared ─────────────────────────────────────────────────────

    def test(self, key: str) -> type[Test[Any]]:
        found = next((one for one in self.tests if one.key == key), None)
        if found is None:
            raise KeyError(f"{self.id} declares no test {key!r}")
        return found

    def command(self, key: str) -> Command:
        found = next((one for one in self.commands if one.key == key), None)
        if found is None:
            raise KeyError(f"{self.id} declares no command {key!r}")
        return found

    def options(self, key: str, input_name: str) -> tuple[dict[str, Any], ...]:
        found = input_named(self._inputs_of(key), input_name)
        if found is None:
            raise KeyError(f"{self.id}.{key} declares no input {input_name!r}")
        return labelled_options(found, self)

    def _inputs_of(self, key: str) -> tuple[Input, ...]:
        if key == LINK_KEY:
            target = getattr(type(self), "target", None)
            return (target,) if isinstance(target, Input) else ()
        if any(one.key == key for one in self.commands):
            return self.command(key).inputs
        test = self.test(key)
        return test.inputs + test.questions

    # ── Whether it may run ───────────────────────────────────────────────────

    def readiness(self, key: str, operator: bool = True) -> Readiness:
        with self._run_lock:
            if self._running is not None:
                return blocked("a test is running")
        return self._readiness_idle(key, operator)

    def _readiness_idle(self, key: str, operator: bool) -> Readiness:
        if any(one.key == key for one in self.commands):
            item = self.command(key)
            needs, guard, asks = item.needs, item.can_run, False
        else:
            test = self.test(key)
            needs, guard, asks = test.needs, test.can_run, bool(test.questions)
        said = _linked_for(needs, self.link_state())
        if not said:
            return said
        if guard is not None:
            try:
                said = answered(guard(self))
            except Exception as exc:
                return blocked(f"{type(exc).__name__}: {exc}")
            if not said:
                return said
        if asks and not operator:
            return blocked("needs an operator")
        return READY

    # ── Running ──────────────────────────────────────────────────────────────

    def run_test(
        self,
        key: str,
        submitted: Mapping[str, Any],
        report: Report,
        operator: bool = False,
    ) -> "RunView":
        test = self.test(key)
        values = coerced_values(test.inputs, submitted, self)
        with self._run_lock:
            if self._running is not None:
                raise NotReady("a test is running")
            said = self._readiness_idle(key, operator)
            if not said:
                raise NotReady(said.reason)
            run = Run(test, self, values, report)
            self._running = run
            self._runs[key] = run
        try:
            run.execute()
        finally:
            run.stop_after(self.stop)
            with self._run_lock:
                self._running = None
            run.done.set()
        from shared.diagnostics.views import run_view

        return run_view(run, self.id)

    def run_command(self, key: str, submitted: Mapping[str, Any]) -> Result:
        item = self.command(key)
        said = self.readiness(key)
        if not said:
            raise NotReady(said.reason)
        values = coerced_values(item.inputs, submitted, self)
        run_log.write_command(f"{self.id}.{key}", values)
        try:
            reply = item.call(self, values)
        except Exception as exc:
            reply = Result(level=Level.ERROR, summary=f"{type(exc).__name__}: {exc}")
        with self._run_lock:
            self._replies[key] = reply
        return reply

    def answer(self, submitted: Any) -> None:
        with self._run_lock:
            run = self._running
        if run is None:
            raise NotReady("no test is running")
        run.answer(submitted)

    def request_stop(self) -> bool:
        with self._run_lock:
            run = self._running
            if run is not None:
                run.stop_requested = time.time()
                run.cancelled.set()
                return True
        self.stop()
        return False

    def cancel(self) -> None:
        with self._run_lock:
            run = self._running
        if run is None:
            return
        run.cancelled.set()
        patience = run.test.ends_within_s()
        if not run.done.wait(patience):
            run_log.log.warning(
                "{} did not finish within {:.0f} s of being cancelled; carrying on "
                "while it still runs",
                run.name,
                patience,
            )

    # ── What was last seen ───────────────────────────────────────────────────

    def running(self) -> Run | None:
        with self._run_lock:
            return self._running

    def last_run(self, key: str) -> Run | None:
        with self._run_lock:
            return self._runs.get(key)

    def last_reply(self, key: str) -> Result | None:
        with self._run_lock:
            return self._replies.get(key)

    def view(self, operator: bool = True) -> "SubsystemView":
        from shared.diagnostics.views import subsystem_view

        return subsystem_view(self, operator)


def _linked_for(needs: Needs, state: LinkState) -> Readiness:
    if needs is Needs.UP and state is not LinkState.UP:
        return blocked("not connected")
    if needs is Needs.DOWN and state in (LinkState.UP, LinkState.LINKING):
        return blocked("the link holds the port; disconnect first")
    return READY
