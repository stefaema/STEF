"""What the operator does to a port before anything holds it.

The obvious ladder is bottom-up: prove the silicon, then prove the firmware. It
resets a healthy board every time you look at it, and the reset kills the
firmware you were about to ask. Ask the app first. When it answers, it has
already said more than the bootloader could, and nothing was disturbed. Only
silence is ambiguous, and only silence is worth a reset to resolve.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from shared import bench_api
from shared.bench_api import (
    FAILED,
    PASSED,
    PRELINK,
    WARNED,
    Abandoned,
    Level,
    Result,
    StepOutcome,
    StepStatus,
)
from transport import fw
from transport.bench import rom
from transport.bench.link import PORT
from transport.transport import AUTO, named_port, pinned_version

STATUS = {
    fw.probe.Finding.RUNNING: PASSED,
    fw.probe.Finding.STALE: WARNED,
    fw.probe.Finding.PROTOCOL: FAILED,
    fw.probe.Finding.ABSENT: FAILED,
}

LEVEL = {
    PASSED: Level.OK,
    WARNED: Level.WARN,
    FAILED: Level.ERROR,
    StepStatus.SKIPPED: Level.OK,
}

DESCRIPTOR = "USB descriptor"
OVER_RPC = "Firmware over RPC"
BOOTLOADER = "ROM bootloader"


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
        raise Abandoned(str(exc), FAILED) from exc


# ── Asking who is there ──────────────────────────────────────────────────────


@bench_api.routine(
    category=PRELINK, steps=[DESCRIPTOR, OVER_RPC, BOOTLOADER], inputs=[PORT]
)
def verify_port(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Verify a port.

    Asks the firmware who it is, and falls back to the ROM bootloader only when
    nothing answers. Ends naming what is on the port and what to do about it.
    """
    port = _port_now(values.get("port", AUTO))

    seen = fw.probe.attached(port)
    assert seen is not None
    status, summary, note = _descriptor_says(seen)
    fields = [("port", port), ("silicon", seen.silicon.value)]
    if seen.vid is not None:
        fields.insert(1, ("usb", seen.vidpid))
    if seen.description:
        fields.insert(-1, ("descriptor", seen.description))
    yield StepOutcome(
        status,
        summary,
        Result(level=LEVEL[status], summary=summary, note=note, fields=tuple(fields)),
        step=DESCRIPTOR,
    )

    verdict = fw.probe.identify(port, pinned_version())
    if verdict.finding is not fw.probe.Finding.SILENT:
        settled = STATUS[verdict.finding]
        raise Abandoned(verdict.sentence, settled, _panel(settled, verdict))
    yield StepOutcome(WARNED, verdict.sentence, step=OVER_RPC)

    try:
        found = rom.detect(port)
    except rom.RomError as exc:
        yield StepOutcome(
            FAILED,
            f"no bootloader answered either, so {port} is not a board we can use",
            Result(level=Level.ERROR, summary=str(exc)),
            step=BOOTLOADER,
        )
        return

    yield StepOutcome(
        WARNED,
        f"{found.description} with no working firmware. Flash it",
        Result(
            level=Level.WARN,
            summary=f"{found.description} answered its bootloader",
            note="The silicon is ours and the firmware is not. Flash it.",
            fields=(("port", port), *found.fields),
        ),
        step=BOOTLOADER,
    )


# ── Putting an image on ──────────────────────────────────────────────────────


@bench_api.routine(
    category=PRELINK,
    hazardous=True,
    inputs=[
        PORT,
        bench_api.choice(
            "image",
            fw.image.versions,
            hint="Which installed version to write. 'auto' is the one this machine pins.",
        ),
        bench_api.boolean(
            "force", hint="Write even when the board already runs this version."
        ),
    ],
)
def flash_board(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Flash the board.

    Erases the flash and writes one installed release onto it, then reads it back
    and asks the firmware who it is. Refuses a board that already runs the chosen
    version unless forced, and refuses a release built for another chip always.
    """
    release = fw.image.resolve(values.get("image", fw.image.AUTO))
    port = _port_now(values.get("port", AUTO))

    altered = fw.image.altered(release)
    if altered:
        raise Abandoned(
            f"{release.version} on disk no longer matches its manifest: "
            f"{', '.join(altered)}. Import it again",
            FAILED,
        )

    running = fw.probe.identify(port, release.version)
    if running.finding is fw.probe.Finding.RUNNING and not values.get("force"):
        raise Abandoned(
            f"{port} already runs {release.version}, so there is nothing to write",
            PASSED,
            Result(level=Level.OK, summary=running.sentence, fields=running.fields),
        )
    yield StepOutcome(
        PASSED,
        f"writing {release.version} to {port}: {running.sentence}",
        _result_for(running),
    )

    found = rom.detect(port)
    if not release.fits(found.chip):
        raise Abandoned(
            f"{release.version} was built for {release.chip} and this board is "
            f"{found.description}. Refusing to write it",
            FAILED,
        )
    yield StepOutcome(
        PASSED,
        f"{found.description}, which is what {release.version} was built for",
        Result(
            level=Level.OK,
            summary="the image matches the silicon",
            fields=found.fields,
        ),
    )

    rom.erase(port, release.chip)
    yield StepOutcome(PASSED, "flash erased")

    for binary in release.binaries:
        rom.write(port, release, binary)
        yield StepOutcome(
            PASSED,
            f"wrote {binary.path.name} at {hex(binary.offset)}, {binary.size} bytes",
        )

    differing = rom.verify(port, release)
    if differing:
        raise Abandoned(
            f"the board reads back different from what was written: "
            f"{', '.join(differing)}",
            FAILED,
        )
    yield StepOutcome(
        PASSED, f"all {len(release.binaries)} images read back as written"
    )

    settled = fw.probe.identify(port, release.version)
    yield StepOutcome(
        PASSED if settled else WARNED, settled.sentence, _result_for(settled)
    )
