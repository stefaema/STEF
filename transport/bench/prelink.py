"""What the operator does to a port before anything holds it.

The obvious ladder is bottom-up: prove the silicon, then prove the firmware. It
resets a healthy board every time you look at it, and the reset kills the
firmware you were about to ask. Ask the app first. When it answers, it has
already said more than the bootloader could, and nothing was disturbed. Only
silence is ambiguous, and only silence is worth a reset to resolve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shared.diagnostics import (
    FAILED,
    PASSED,
    WARNED,
    Failed,
    Needs,
    StepStatus,
    Test,
    step,
)
from shared.subsystem import Level, Result, Table, boolean, choice
from transport import fw
from transport.bench import rom
from transport.bench.link import PORT
from transport.transport import AUTO, named_port

if TYPE_CHECKING:
    from transport.subsystem import Transport

STATUS = {
    fw.probe.Finding.RUNNING: PASSED,
    fw.probe.Finding.INCOMPATIBLE: FAILED,
    fw.probe.Finding.ABSENT: FAILED,
}

LEVEL = {
    PASSED: Level.OK,
    WARNED: Level.WARN,
    FAILED: Level.ERROR,
    StepStatus.SKIPPED: Level.OK,
    StepStatus.ERROR: Level.ERROR,
}

DESCRIPTOR = "USB descriptor"
OVER_RPC = "Firmware over RPC"
BOOTLOADER = "ROM bootloader"

RELEASE = "Release"
BOARD = "Board"
CHIP = "Chip"
ERASE = "Erase"
WRITE = "Write"
READ_BACK = "Read back"
FIRMWARE = "Firmware"


def _panel(status: StepStatus, verdict: fw.probe.Verdict) -> Result:
    """Return a verdict as the panel behind the one-line outcome."""
    return Result(level=LEVEL[status], summary=verdict.sentence, fields=verdict.fields)


def _result_for(verdict: fw.probe.Verdict) -> Result:
    """Return a verdict as the panel behind the line that reports it."""
    return Result(
        level=Level.OK if verdict else Level.WARN,
        summary=verdict.sentence,
        fields=verdict.fields,
    )


def _descriptor_says(seen: fw.probe.Candidate) -> tuple[StepStatus, str, str]:
    """Return how far the descriptor gets, which for most ports is nowhere.

    Never a failure. Naming a port is the operator overruling the shortlist, and
    the descriptor has no standing to refuse: the tiers below it are the ones
    that can answer.
    """
    if seen.silicon is fw.probe.Silicon.ESPRESSIF:
        return (
            PASSED,
            f"{seen.device} is Espressif silicon, {seen.description or seen.vidpid}",
            "The vendor id is Espressif's own, so this much is settled.",
        )
    if seen.silicon is fw.probe.Silicon.BRIDGE:
        return (
            PASSED,
            f"{seen.device} is a USB-UART bridge, {seen.description or seen.vidpid}",
            "A bridge chip names itself, never what is behind it.",
        )
    return (
        WARNED,
        f"{seen.device} does not look like a board",
        "Nothing in the descriptor suggests one. Asking anyway, since a "
        "descriptor cannot settle what is on the far side of a UART.",
    )


def _port_now(chosen: str) -> str:
    """Return the port to work on, refusing before anything is opened."""
    try:
        return fw.probe.find_port(named_port(chosen))
    except fw.link.LinkError as exc:
        raise Failed(str(exc)) from exc


# ── Asking who is there ──────────────────────────────────────────────────────


class VerifyPort(Test[Any]):
    """Verify a port.

    Asks the firmware who it is, and falls back to the ROM bootloader only when
    nothing answers. Ends naming what is on the port and what to do about it.
    """

    sub: Transport
    needs = Needs.DOWN
    inputs = (PORT,)

    @step(DESCRIPTOR)
    def descriptor(self) -> None:
        self.port = _port_now(self.values.get("port", AUTO))
        seen = fw.probe.attached(self.port)
        assert seen is not None
        status, summary, note = _descriptor_says(seen)
        fields = [("port", self.port), ("silicon", seen.silicon.value)]
        if seen.vid is not None:
            fields.insert(1, ("usb", seen.vidpid))
        if seen.description:
            fields.insert(-1, ("descriptor", seen.description))
        said = self.warn if status is WARNED else self.report
        said(
            summary,
            Result(
                level=LEVEL[status], summary=summary, note=note, fields=tuple(fields)
            ),
        )

    @step(OVER_RPC)
    def over_rpc(self) -> None:
        verdict = fw.probe.identify(self.port)
        if verdict.finding is not fw.probe.Finding.SILENT:
            settled = STATUS[verdict.finding]
            self.finish(verdict.sentence, settled, _panel(settled, verdict))
        self.warn(verdict.sentence)

    @step(BOOTLOADER, skippable=True)
    def bootloader(self) -> None:
        try:
            found = rom.detect(self.port)
        except rom.RomError as exc:
            raise Failed(
                f"no bootloader answered either, so {self.port} is not a board we can use",
                Result(level=Level.ERROR, summary=str(exc)),
            ) from exc
        self.warn(
            f"{found.description} with no working firmware. Flash it",
            Result(
                level=Level.WARN,
                summary=f"{found.description} answered its bootloader",
                note="The silicon is ours and the firmware is not. Flash it.",
                fields=(("port", self.port), *found.fields),
            ),
        )


# ── Putting an image on ──────────────────────────────────────────────────────


class FlashBoard(Test[Any]):
    """Flash the board.

    Erases the flash and writes one installed release onto it, then reads it back
    and asks the firmware who it is. Refuses a board that already runs the chosen
    version unless forced, and refuses a release built for another chip always.
    """

    sub: Transport
    needs = Needs.DOWN
    inputs = (
        PORT,
        choice(
            "image",
            lambda sub: fw.image.versions(),
            hint="Which installed version to write. 'auto' is the one this machine pins.",
        ),
        boolean("force", hint="Write even when the board already runs this version."),
    )

    @step(RELEASE)
    def release(self) -> None:
        self.chosen = fw.image.resolve(self.values.get("image", fw.image.AUTO))
        self.port = _port_now(self.values.get("port", AUTO))
        altered = fw.image.altered(self.chosen)
        if altered:
            raise Failed(
                f"{self.chosen.version} on disk no longer matches its manifest: "
                f"{', '.join(altered)}. Import it again"
            )
        self.report(f"{self.chosen.version}, as installed, matches its manifest")

    @step(BOARD)
    def board(self) -> None:
        running = fw.probe.identify(self.port)
        if running.version == self.chosen.version and not self.values.get("force"):
            self.finish(
                f"{self.port} already runs {self.chosen.version}, so there is nothing to write",
                PASSED,
                Result(level=Level.OK, summary=running.sentence, fields=running.fields),
            )
        self.report(
            f"writing {self.chosen.version} to {self.port}: {running.sentence}",
            _result_for(running),
        )

    @step(CHIP)
    def chip(self) -> None:
        found = rom.detect(self.port)
        if not self.chosen.fits(found.chip):
            raise Failed(
                f"{self.chosen.version} was built for {self.chosen.chip} and this board is "
                f"{found.description}. Refusing to write it"
            )
        self.report(
            f"{found.description}, which is what {self.chosen.version} was built for",
            Result(
                level=Level.OK,
                summary="the image matches the silicon",
                fields=found.fields,
            ),
        )

    @step(ERASE, hazard="erases the board's flash")
    def erase(self) -> None:
        rom.erase(self.port, self.chosen.chip)
        self.report("flash erased")

    @step(WRITE, hazard="writes a new firmware onto the board")
    def write(self) -> None:
        rows = []
        for binary in self.chosen.binaries:
            rom.write(self.port, self.chosen, binary)
            rows.append((binary.path.name, hex(binary.offset), str(binary.size)))
        self.report(
            f"wrote {len(rows)} images",
            Result(
                level=Level.OK,
                summary=f"{len(rows)} images written",
                table=Table(head=("image", "offset", "bytes"), rows=tuple(rows)),
            ),
        )

    @step(READ_BACK)
    def read_back(self) -> None:
        differing = rom.verify(self.port, self.chosen)
        if differing:
            raise Failed(
                f"the board reads back different from what was written: "
                f"{', '.join(differing)}"
            )
        self.report(f"all {len(self.chosen.binaries)} images read back as written")

    @step(FIRMWARE)
    def firmware(self) -> None:
        settled = fw.probe.identify(self.port)
        said = self.report if settled else self.warn
        said(settled.sentence, _result_for(settled))
