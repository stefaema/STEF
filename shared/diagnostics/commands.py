from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from shared.diagnostics.records import Needs
from shared.subsystem import (
    Input,
    Readiness,
    Result,
    checked_inputs,
    prose_of,
    titled,
)

Call = Callable[[Any, dict[str, Any]], Result]


@dataclass(frozen=True, slots=True)
class Command:
    group: str
    name: str
    title: str
    description: str
    call: Call
    inputs: tuple[Input, ...] = ()
    needs: Needs = Needs.UP
    hazard: str | None = None
    can_run: Callable[[Any], Readiness | None] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", checked_inputs(self.inputs))

    @property
    def key(self) -> str:
        return f"{self.group}.{self.name}"


def command(
    *,
    inputs: Sequence[Input] = (),
    needs: Needs = Needs.UP,
    hazard: str | None = None,
    can_run: Callable[[Any], Readiness | None] | None = None,
) -> Callable[[Call], Command]:
    def declare(call: Call) -> Command:
        summary, body = prose_of(call)
        return Command(
            group=call.__module__.rpartition(".")[2],
            name=call.__name__,
            title=titled(summary) or call.__name__,
            description=body,
            call=call,
            inputs=tuple(inputs),
            needs=needs,
            hazard=hazard,
            can_run=can_run,
        )

    return declare
