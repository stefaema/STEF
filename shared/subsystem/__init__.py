"""Vocabulary to describe a STEF subsystem and its link state."""

import enum
import inspect
from dataclasses import dataclass
from types import ModuleType
from typing import Any

# What a subsystem package is asked for its link state by.
LINK_STATE_ATTRIBUTE = "link_state"


class SubsystemLinkState(enum.Enum):
    """Whether one subsystem is reachable."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"


def link_state_of(module: Any) -> SubsystemLinkState:
    """Return the state a subsystem package reports, or DOWN where it reports none.

    Asked through the module rather than through a function captured at load, so
    a package that reports differently later is believed.
    """
    reported = getattr(module, LINK_STATE_ATTRIBUTE, None)
    return reported() if reported is not None else SubsystemLinkState.DOWN


# ── The prose a package states about itself ──────────────────────────────────


def prose_of(target: Any) -> tuple[str, str]:
    """Return a docstring's summary line and its body, which is what the screen shows."""
    return summary_and_body(inspect.getdoc(target) or "")


def summary_and_body(prose: str) -> tuple[str, str]:
    """Return any prose split into the line a label shows and the rest of it.

    A screen gives the two different weights, so prose that arrives whole reads
    as one long label unless it is split here.
    """
    summary, _, body = prose.partition("\n")
    return summary.strip(), inspect.cleandoc(body).strip()


def titled(summary: str) -> str:
    """Return a docstring summary as a title, which is a label and not a sentence."""
    return (
        summary[:-1]
        if summary.endswith(".") and not summary.endswith("..")
        else summary
    )


# ── Which part of the machine this is ────────────────────────────────────────


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
    "LINK_STATE_ATTRIBUTE",
    "SubsystemSpec",
    "SubsystemLinkState",
    "prose_of",
    "link_state_of",
    "summary_and_body",
    "titled",
]
