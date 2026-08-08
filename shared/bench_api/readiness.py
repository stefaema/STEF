"""Whether something may proceed, and why not when it may not."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Readiness:
    """A verdict on whether a control may be used, carrying the reason when it may not."""

    reason: str | None = None

    def __bool__(self) -> bool:
        """Return whether this may proceed."""
        return self.reason is None

    def __str__(self) -> str:
        """Return the reason, empty when there is none."""
        return self.reason or ""


READY = Readiness()


def blocked(reason: str) -> Readiness:
    """Return a refusal carrying the sentence an operator reads."""
    return Readiness(reason)
