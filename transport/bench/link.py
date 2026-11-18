"""The port the link opens, and whether our firmware is answering on it."""

from typing import Any

from shared.subsystem import READY, Option, Readiness, blocked, choice
from transport import fw
from transport.transport import AUTO, named_port


def serial_ports(sub: Any = None) -> tuple[Option, ...]:
    """Return every attached port, each with a label saying what it looks like.

    Every port, not only the shortlist. What the descriptor settles is what
    `auto` may pick, never what an operator may choose, and a board behind a
    bridge nobody recognises is exactly the case where naming the port by hand is
    the way through. The likely ones sort first so the list reads as a
    recommendation rather than a filter.
    """
    ranked = sorted(fw.probe.candidates(), key=lambda c: (not c.plausible, c.device))
    return (Option(AUTO, AUTO), *(Option(c.device, _label(c)) for c in ranked))


def _label(candidate: fw.probe.Candidate) -> str:
    """Return what to call one port, which is its name plus whatever it admits to."""
    if not candidate.plausible:
        return candidate.device
    return f"{candidate.device} ({candidate.description or candidate.vidpid})"


PORT = choice(
    "port",
    serial_ports,
    hint="Which port the board is on. 'auto' when it is the only one.",
)


# ── Whether there is anything to open ────────────────────────────────────────


def can_connect(port: str = AUTO) -> Readiness:
    """Say whether our firmware is answering on this port, and what is there when not.

    Asks rather than remembering whether a verify panel was run. A remembered
    answer goes stale on the next replug, and the refusal an operator can act on
    is the one that names what it found.
    """
    try:
        chosen = fw.probe.find_port(named_port(port))
    except fw.link.LinkError as exc:
        return blocked(str(exc))
    verdict = fw.probe.identify(chosen)
    return READY if verdict else blocked(verdict.sentence)
