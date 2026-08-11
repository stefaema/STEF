"""Who is on the port, told in the order that costs the board least.

The obvious ladder is bottom-up: prove the silicon, then prove the firmware. It
resets a healthy board every time you look at it, and the reset kills the
firmware you were about to ask. Ask the app first. When it answers, it has
already said more than the bootloader could, and nothing was disturbed. Only
silence is ambiguous, and only silence is worth a reset to resolve.
"""

from __future__ import annotations

from shared import bench_api
from shared.bench_api import Level, Result, StepOutcome, StepStatus
from transport import fw_image, fw_link, fw_probe
from transport.bench import rom
from transport.transport import AUTO, serial_ports

STATUS = {
    fw_probe.Finding.RUNNING: StepStatus.PASSED,
    fw_probe.Finding.STALE: StepStatus.WARNED,
    fw_probe.Finding.PROTOCOL: StepStatus.FAILED,
    fw_probe.Finding.ABSENT: StepStatus.FAILED,
}

LEVEL = {
    StepStatus.PASSED: Level.OK,
    StepStatus.WARNED: Level.WARN,
    StepStatus.FAILED: Level.ERROR,
    StepStatus.SKIPPED: Level.OK,
}


def _result(status: StepStatus, verdict: fw_probe.Verdict) -> Result:
    """Return the verdict as the panel behind the one-line outcome."""
    return Result(level=LEVEL[status], summary=verdict.sentence, fields=verdict.fields)


def _descriptor_says(seen: fw_probe.Candidate) -> tuple[StepStatus, str, str]:
    """Return how far the descriptor gets, which for most ports is nowhere.

    Never a failure. Naming a port is the operator overruling the shortlist, and
    the descriptor has no standing to refuse: the tiers below it are the ones
    that can answer.
    """
    if seen.silicon is fw_probe.Silicon.ESPRESSIF:
        return (
            StepStatus.PASSED,
            f"{seen.device} is Espressif silicon, {seen.description or seen.vidpid}",
            "The vendor id is Espressif's own, so this much is settled.",
        )
    if seen.silicon is fw_probe.Silicon.BRIDGE:
        return (
            StepStatus.PASSED,
            f"{seen.device} is a USB-UART bridge, {seen.description or seen.vidpid}",
            "A bridge chip names itself, never what is behind it.",
        )
    return (
        StepStatus.WARNED,
        f"{seen.device} does not look like a board",
        "Nothing in the descriptor suggests one. Asking anyway, since a "
        "descriptor cannot settle what is on the far side of a UART.",
    )


def _pinned() -> str | None:
    """Return the version this machine says it runs, treating a bad pin as none.

    A malformed pin must not stop the ladder: the operator is here because
    something is wrong, and refusing to look would be the least useful moment
    to be strict.
    """
    try:
        return fw_image.expected()
    except fw_image.ImageError:
        return None


@bench_api.link_test(
    params=(
        bench_api.choice(
            "port",
            serial_ports,
            hint="Which port to interrogate. 'auto' when only one could carry a board.",
        ),
    )
)
class VerifyPort:
    """Verify a port.

    Asks the firmware who it is, and falls back to the ROM bootloader only when
    nothing answers. Ends naming what is on the port and what to do about it.
    """

    def __init__(self, port: str = AUTO) -> None:
        """Take the port the form chose, which every step below reads off self."""
        self.chosen = port
        self.port = ""
        self.verdict: fw_probe.Verdict | None = None

    @bench_api.step
    def attached(self, bench: object) -> StepOutcome:
        """USB descriptor."""
        try:
            self.port = fw_probe.find_port(None if self.chosen == AUTO else self.chosen)
        except fw_link.LinkError as exc:
            raise bench_api.Abandoned(str(exc), StepStatus.FAILED) from exc

        seen = fw_probe.attached(self.port)
        assert seen is not None
        status, summary, note = _descriptor_says(seen)
        fields = [("port", self.port), ("silicon", seen.silicon.value)]
        if seen.vid is not None:
            fields.insert(1, ("usb", seen.vidpid))
        if seen.description:
            fields.insert(-1, ("descriptor", seen.description))

        return StepOutcome(
            status,
            summary,
            Result(
                level=LEVEL[status], summary=summary, note=note, fields=tuple(fields)
            ),
        )

    @bench_api.step
    def firmware(self, bench: object) -> StepOutcome:
        """Firmware over RPC."""
        self.verdict = fw_probe.identify(self.port, _pinned())
        if self.verdict.finding is fw_probe.Finding.SILENT:
            return StepOutcome(StepStatus.WARNED, self.verdict.sentence)

        settled = STATUS[self.verdict.finding]
        raise bench_api.Abandoned(
            self.verdict.sentence, settled, _result(settled, self.verdict)
        )

    @bench_api.step
    def bootloader(self, bench: object) -> StepOutcome:
        """ROM bootloader."""
        try:
            found = rom.detect(self.port)
        except rom.RomError as exc:
            return StepOutcome(
                StepStatus.FAILED,
                f"no bootloader answered either, so {self.port} is not a board "
                f"we can use",
                Result(level=Level.ERROR, summary=str(exc)),
            )

        return StepOutcome(
            StepStatus.WARNED,
            f"{found.description} with no working firmware. Flash it",
            Result(
                level=Level.WARN,
                summary=f"{found.description} answered its bootloader",
                note="The silicon is ours and the firmware is not. Flash it.",
                fields=(("port", self.port), *found.fields),
            ),
        )
