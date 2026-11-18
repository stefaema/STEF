import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shared import logs
from shared.diagnostics import run_log
from shared.diagnostics.records import (
    CANCELLED,
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    WARNED,
    Cancelled,
    Failed,
    Measurement,
    NoAnswer,
    Prompt,
    PromptClosed,
    SkipReason,
    StepOutcome,
    StepStatus,
    StopUnconfirmed,
    verdict,
)
from shared.diagnostics.steps import Finish, Skip, StepSpec, Test
from shared.subsystem import DeclarationError, Input, Level, NotReady, Result, coerced

Report = Callable[[StepOutcome | Prompt | PromptClosed | Result], None]

POLL = 0.1


@dataclass
class _Pending:
    detail: str = ""
    result: Result | None = None
    warned: bool = False
    measurements: list[Measurement] = field(default_factory=list)
    answers: list[tuple[str, Any]] = field(default_factory=list)


class Run:
    def __init__(
        self,
        test: type[Test[Any]],
        sub: Any,
        values: dict[str, Any],
        report: Report,
    ) -> None:
        self.test = test
        self.sub = sub
        self.values = values
        self.report = report
        self.name = f"{sub.id}.{test.key}"
        self.started = time.time()
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.stop_requested: float | None = None
        self.stopped: Result | None = None
        self.stop_unconfirmed: str | None = None
        self.outcomes: list[StepOutcome] = []
        self.prompt: Prompt | None = None
        self._lock = threading.Lock()
        self._answered = threading.Event()
        self._answer: Any = None
        self._step = ""
        self._pending = _Pending()
        self._in_end = False

    # ── What a step calls ────────────────────────────────────────────────────

    def said(self, detail: str, result: Result | None, warned: bool) -> None:
        self._pending.detail = detail
        if result is not None:
            self._pending.result = result
        self._pending.warned = self._pending.warned or warned

    def measured(
        self,
        name: str,
        value: Any,
        unit: str | None,
        low: float | None,
        high: float | None,
        expected: Any,
    ) -> None:
        self._pending.measurements.append(
            Measurement(name, value, unit, low, high, expected)
        )

    def checkpoint(self) -> None:
        if self.cancelled.is_set() and not self._in_end:
            raise Cancelled()

    def ask(self, question: Input, timeout: float) -> Any:
        if question not in self.test.questions:
            raise DeclarationError(
                f"{question.name!r} is not a question {self.test.key} declares"
            )
        self.checkpoint()
        asked = Prompt(self.test.key, self._step, question, timeout)
        with self._lock:
            self._answered.clear()
            self.prompt = asked
        self._tell(asked)
        deadline = time.monotonic() + timeout
        try:
            while not self._answered.wait(POLL):
                self.checkpoint()
                if time.monotonic() > deadline:
                    raise NoAnswer(f"no answer within {timeout:.0f} s")
        finally:
            with self._lock:
                self.prompt = None
            self._tell(PromptClosed(self.test.key, asked.step))
        value = coerced(question, self._answer, self.sub)
        self._pending.answers.append((question.name, value))
        return value

    def answer(self, submitted: Any) -> None:
        with self._lock:
            if self.prompt is None:
                raise NotReady("nothing is being asked")
            self._answer = submitted
            self._answered.set()

    # ── Running ──────────────────────────────────────────────────────────────

    def execute(self) -> None:
        with logs.logger.contextualize(routine=self.name, started=run_log.start_time()):
            run_log.write_start(self.name, self.values)
            began = time.monotonic()
            try:
                self._steps()
            finally:
                statuses = [one.status for one in self.outcomes]
                if self.cut_short():
                    statuses.append(CANCELLED)
                run_log.write_end(self.name, statuses, time.monotonic() - began)

    def _steps(self) -> None:
        instance = self.test(self.sub, self.values, self)
        stopped: SkipReason | None = None
        for spec in self.test.steps:
            if stopped is None and self.cancelled.is_set():
                stopped = SkipReason.CANCELLED
            if stopped is not None:
                self._settle(StepOutcome(spec.title, SKIPPED, skipped=stopped))
                continue
            outcome, stopped = self._step_once(instance, spec)
            self._settle(outcome)
        if self.test.end_step is not None:
            self._in_end = True
            outcome, _ = self._step_once(instance, self.test.end_step)
            self._settle(outcome)

    def _step_once(
        self, instance: Test[Any], spec: StepSpec
    ) -> tuple[StepOutcome, SkipReason | None]:
        self._step = spec.title
        self._pending = pending = _Pending()
        stop: SkipReason | None = None
        skipped: SkipReason | None = None
        try:
            getattr(instance, spec.method)()
            status = WARNED if pending.warned else PASSED
            detail = pending.detail
        except Finish as done:
            status, detail = done.status, done.detail
            if done.result is not None:
                pending.result = done.result
            stop = (
                SkipReason.NOT_REACHED
                if done.status in (FAILED, ERROR)
                else SkipReason.NOT_NEEDED
            )
        except Skip as skip:
            status, detail, skipped = SKIPPED, skip.detail, SkipReason.NOT_NEEDED
        except Cancelled:
            status, detail, stop = CANCELLED, "", SkipReason.CANCELLED
        except NoAnswer as exc:
            status, detail, stop = CANCELLED, str(exc), SkipReason.CANCELLED
        except Failed as failed:
            status, detail = FAILED, failed.detail
            if failed.result is not None:
                pending.result = failed.result
        except Exception as exc:
            status, detail = FAILED, f"{type(exc).__name__}: {exc}"

        outside = [one for one in pending.measurements if not one.within]
        if outside and status in (PASSED, WARNED):
            status = FAILED
            detail = "; ".join(
                f"{one.name} {one.value!r} outside {one.limits()}" for one in outside
            )
        if spec.end and status is FAILED:
            status = ERROR
        if status is FAILED and stop is None and not spec.continue_on_failure:
            stop = SkipReason.NOT_REACHED

        return (
            StepOutcome(
                step=spec.title,
                status=status,
                detail=detail,
                skipped=skipped,
                result=pending.result,
                measurements=tuple(pending.measurements),
                answers=tuple(pending.answers),
                end=spec.end,
            ),
            stop,
        )

    def _settle(self, outcome: StepOutcome) -> None:
        with self._lock:
            self.outcomes.append(outcome)
        run_log.write_step(outcome)
        self._tell(outcome)

    def stop_after(self, stop: Callable[[], None] | None) -> None:
        """Call stop if a stop was requested. stop is None for a test that holds no link."""
        if self.stop_requested is None:
            return
        if stop is None:
            self.stopped = Result(
                level=Level.OK,
                summary="cancelled at the next step. This test holds no link, "
                "so no stop was sent",
            )
            run_log.log.info("{}: {}", self.name, self.stopped.summary)
            self._tell(self.stopped)
            return
        try:
            self.stopped = stopped_by(stop, self.name)
        except StopUnconfirmed as unconfirmed:
            self.mark_stop_unconfirmed(unconfirmed)
            return
        self._tell(self.stopped)

    def mark_stop_unconfirmed(self, unconfirmed: StopUnconfirmed) -> None:
        """Record that the stop did not reach the hardware, log it at ERROR and report it."""
        self.stop_unconfirmed = str(unconfirmed)
        self.stopped = Result(level=Level.ERROR, summary=str(unconfirmed))
        run_log.log.error("{}: {}", self.name, unconfirmed)
        self._tell(self.stopped)

    def _tell(self, record: StepOutcome | Prompt | PromptClosed | Result) -> None:
        try:
            self.report(record)
        except Exception as exc:
            run_log.log.warning("a report listener failed: {}", exc)

    # ── What a screen reads ──────────────────────────────────────────────────

    def settled(self) -> tuple[StepOutcome, ...]:
        with self._lock:
            return tuple(self.outcomes)

    def verdict(self) -> StepStatus | None:
        if not self.done.is_set():
            return None
        found = verdict([one.status for one in self.settled()])
        if self.cut_short() and found in (WARNED, PASSED, SKIPPED):
            return CANCELLED
        return found

    def cut_short(self) -> bool:
        return any(
            one.status is CANCELLED or one.skipped is SkipReason.CANCELLED
            for one in self.settled()
        )


def stopped_by(stop: Callable[[], None], name: str) -> Result:
    """Call stop and return a Result that says whether it succeeded. StopUnconfirmed is re-raised."""
    try:
        stop()
    except StopUnconfirmed:
        raise
    except Exception as exc:
        run_log.log.error("{}: stopping failed: {}: {}", name, type(exc).__name__, exc)
        return Result(
            level=Level.ERROR, summary=f"stopping failed: {type(exc).__name__}: {exc}"
        )
    run_log.log.info("{}: stopped the hardware", name)
    return Result(level=Level.OK, summary="stopped the hardware")
