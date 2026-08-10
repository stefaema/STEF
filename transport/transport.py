"""The subsystem the bench sees, and the link it is reached through."""

from __future__ import annotations

from typing import Any

from shared import bench_api
from shared.bench_api import READY, Option, Readiness, SubsystemState, blocked
from transport import fw_image, fw_link, fw_probe

AUTO = "auto"


def serial_ports() -> tuple[Option, ...]:
    """Return every attached port, each with a label saying what it looks like.

    Every port, not only the shortlist. What the descriptor settles is what
    `auto` may pick, never what an operator may choose, and a board behind a
    bridge nobody recognises is exactly the case where naming the port by hand is
    the way through. The likely ones sort first so the list reads as a
    recommendation rather than a filter.
    """
    ranked = sorted(fw_probe.candidates(), key=lambda c: (not c.plausible, c.device))
    return (
        Option(AUTO, AUTO),
        *(Option(c.device, _label(c)) for c in ranked),
    )


def _label(candidate: fw_probe.Candidate) -> str:
    """Return what to call one port, which is its name plus whatever it admits to."""
    if not candidate.plausible:
        return candidate.device
    return f"{candidate.device} ({candidate.description or candidate.vidpid})"


def _named(port: str) -> str | None:
    """Return the port the operator chose, or None where they left the choice open."""
    return None if port == AUTO else port


def _pinned() -> str | None:
    """Return the version this machine says it runs, treating an unreadable pin as none."""
    try:
        return fw_image.expected()
    except fw_image.ImageError:
        return None


@bench_api.subsystem(
    "transport",
    """
    The film transport, over USB.

    One board carrying the stepper drivers, reached by the RPC protocol the firmware
    serves.
    """,
)
class Transport:
    """Owns the link, and answers for the subsystem's state by asking it."""

    def __init__(self, link: TransportLink | None = None) -> None:
        """Start with a link that has not connected yet."""
        self.link = link if link is not None else TransportLink()

    @property
    def state(self) -> SubsystemState:
        """Return whether the board is reachable, which only the link knows."""
        return self.link.state

    @property
    def firmware(self) -> Any:
        """Return the open `FirmwareLink`, or None while there is no link."""
        return self.link.firmware


@bench_api.link(
    params=(
        bench_api.choice(
            "port",
            serial_ports,
            hint="Which port the board is on. 'auto' when it is the only one.",
        ),
    )
)
class TransportLink:
    """The USB connection to the board, opened and closed as a whole."""

    def __init__(self, *, on_log: Any = None) -> None:
        """Start disconnected, holding the sink the firmware's logs will go to."""
        self._on_log = on_log
        self._firmware: Any = None
        self._failure: str | None = None

    @property
    def firmware(self) -> Any:
        """Return the open `FirmwareLink`, or None while there is no link."""
        return self._firmware

    @property
    def state(self) -> SubsystemState:
        """Return the state the link is in, which is what having one says."""
        if self._firmware is not None:
            return SubsystemState.UP
        return SubsystemState.ERROR if self._failure else SubsystemState.DOWN

    def can_connect(self, port: str = AUTO) -> Readiness:
        """Say whether our firmware is answering on this port, and what is there when not.

        Asks rather than remembering whether a verify panel was run. A remembered
        answer goes stale on the next replug, and the refusal an operator can act
        on is the one that names what it found.
        """
        if self._firmware is not None:
            return blocked("already connected")
        try:
            chosen = fw_probe.find_port(_named(port))
        except fw_link.LinkError as exc:
            return blocked(str(exc))

        verdict = fw_probe.identify(chosen, _pinned())
        return READY if verdict else blocked(verdict.sentence)

    def connect(self, port: str = AUTO) -> None:
        """Open the link, atomically, so a half-open one is not representable."""
        chosen = fw_probe.find_port(_named(port))
        try:
            firmware = fw_link.FirmwareLink(chosen, on_log=self._on_log)
        except Exception as exc:
            self._failure = f"{type(exc).__name__}: {exc}"
            raise
        self._failure = None
        self._firmware = firmware

    def can_disconnect(self) -> Readiness:
        """Say whether there is a link to close."""
        return READY if self._firmware is not None else blocked("not connected")

    def disconnect(self) -> None:
        """Close the link and everything it started, whatever state it was in."""
        firmware, self._firmware = self._firmware, None
        self._failure = None
        if firmware is not None:
            firmware.close()
