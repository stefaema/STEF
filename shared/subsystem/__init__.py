"""Vocabulary to describe a STEF subsystem, its link, and what it shows a screen."""

from dataclasses import dataclass
from types import ModuleType
from typing import Any

from shared.subsystem.inputs import (
    KINDS,
    Kind,
    as_bytes,
    bitmask,
    blank_values,
    boolean,
    checked_inputs,
    choice,
    coerced,
    coerced_values,
    confirmation,
    current_options,
    group,
    input_named,
    inputs_for,
    integer,
    labelled_options,
    options_are_live,
    overridden,
    raw_bytes,
    truthy,
)
from shared.subsystem.prose import prose_of, summary_and_body, titled
from shared.subsystem.records import (
    READY,
    DeclarationError,
    Input,
    Level,
    Option,
    Options,
    Readiness,
    Result,
    Table,
    answered,
    blocked,
)
from shared.subsystem.subsystem import (
    Linked,
    LinkState,
    NotLinked,
    NotReady,
    Subsystem,
)

SubsystemLinkState = LinkState

# What a subsystem package is asked for its link state by.
LINK_STATE_ATTRIBUTE = "link_state"


def link_state_of(module: Any) -> LinkState:
    """Return the state a subsystem package reports, or DOWN where it reports none.

    Asked through the module rather than through a function captured at load, so
    a package that reports differently later is believed.
    """
    reported = getattr(module, LINK_STATE_ATTRIBUTE, None)
    return reported() if reported is not None else LinkState.DOWN


@dataclass(frozen=True, slots=True)
class SubsystemSpec:
    """Which part of the machine a package is, and the prose a screen labels it with."""

    id: str
    package: str
    summary: str = ""
    description: str = ""

    @classmethod
    def of(cls, module: ModuleType) -> "SubsystemSpec":
        """Return the identity a loaded package states, its name and its docstring."""
        summary, description = prose_of(module)
        package = module.__name__
        return cls(
            id=package.rpartition(".")[2],
            package=package,
            summary=summary,
            description=description,
        )

    def owns(self, module_name: str) -> bool:
        """Whether a module was written inside this subsystem's package."""
        return module_name == self.package or module_name.startswith(f"{self.package}.")


__all__ = [
    "KINDS",
    "LINK_STATE_ATTRIBUTE",
    "READY",
    "DeclarationError",
    "Input",
    "Kind",
    "Level",
    "LinkState",
    "Linked",
    "NotLinked",
    "NotReady",
    "Option",
    "Options",
    "Readiness",
    "Result",
    "Subsystem",
    "SubsystemLinkState",
    "SubsystemSpec",
    "Table",
    "answered",
    "as_bytes",
    "bitmask",
    "blank_values",
    "blocked",
    "boolean",
    "checked_inputs",
    "choice",
    "coerced",
    "coerced_values",
    "confirmation",
    "current_options",
    "group",
    "input_named",
    "inputs_for",
    "integer",
    "labelled_options",
    "link_state_of",
    "options_are_live",
    "overridden",
    "prose_of",
    "raw_bytes",
    "summary_and_body",
    "titled",
    "truthy",
]
