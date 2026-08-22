"""What Transport, Capture and Detection have in common."""

import enum
import importlib
import inspect
from dataclasses import dataclass
from typing import Any

# What a subsystem package is asked for its state by.
STATE_ATTRIBUTE = "state"


class SubsystemState(enum.Enum):
    """Whether one subsystem is reachable."""

    DOWN = "down"
    LINKING = "linking"
    UP = "up"
    ERROR = "error"


def state_of(module: Any) -> SubsystemState:
    """Return the state a subsystem package reports, or DOWN where it reports none.

    Asked through the module rather than through a function captured at load, so
    a package that reports differently later is believed.
    """
    reported = getattr(module, STATE_ATTRIBUTE, None)
    return reported() if reported is not None else SubsystemState.DOWN


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
    def of(cls, module: Any) -> "SubsystemSpec":
        """Return the identity a loaded package states, its name and its docstring."""
        summary, description = prose_of(module)
        package = str(module.__name__)
        return cls(
            id=package.rpartition(".")[2],
            package=package,
            summary=summary,
            description=description,
        )

    @classmethod
    def of_package(cls, package: str) -> "SubsystemSpec":
        """Return the identity of a package named rather than held."""
        return cls.of(importlib.import_module(package))

    def owns(self, module: str) -> bool:
        """Whether a module was written inside this subsystem's package."""
        return module == self.package or module.startswith(f"{self.package}.")


__all__ = [
    "STATE_ATTRIBUTE",
    "SubsystemSpec",
    "SubsystemState",
    "prose_of",
    "state_of",
    "summary_and_body",
    "titled",
]
