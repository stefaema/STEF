import inspect
from typing import Any


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
