"""Putting an image on a board, and refusing when the board already has it.

The tempting way to keep an operator from flashing needlessly is to make them
run the verify panel first. That is a rule to remember, it goes stale the moment
anything is replugged, and it needs state kept between two runs. So this asks
again itself. Deciding from what the board says right now costs one round trip
and leaves no ordering to teach: press it whenever, and it will say if it was
not needed.

The generator form, because how many binaries a release has is the release's
business, and each one should land as its own line rather than inside a silence.
"""

from __future__ import annotations

from collections.abc import Iterator

from shared import bench_api
from shared.bench_api import Level, Result, StepOutcome, StepStatus
from transport import fw_image, fw_probe
from transport.bench import rom
from transport.transport import AUTO, serial_ports


def _ok(summary: str, **named: str) -> Result:
    """Return the panel behind a step that went as it should."""
    return Result(level=Level.OK, summary=summary, fields=tuple(named.items()))


@bench_api.link_test(
    hazardous=True,
    params=(
        bench_api.choice(
            "port",
            serial_ports,
            hint="Which port the board is on. 'auto' when only one could carry a board.",
        ),
        bench_api.choice(
            "image",
            fw_image.versions,
            hint="Which installed version to write. 'auto' is the one this machine pins.",
        ),
        bench_api.boolean(
            "force",
            hint="Write even when the board already runs this version.",
        ),
    ),
)
def flash_board(
    bench: object, port: str = AUTO, image: str = fw_image.AUTO, force: bool = False
) -> Iterator[StepOutcome]:
    """Flash the board.

    Erases the flash and writes one installed release onto it, then reads it back
    and asks the firmware who it is. Refuses a board that already runs the chosen
    version unless forced, and refuses a release built for another chip always.
    """
    release = fw_image.resolve(image)
    chosen = fw_probe.find_port(None if port == AUTO else port)

    altered = fw_image.altered(release)
    if altered:
        raise bench_api.Abandoned(
            f"{release.version} on disk no longer matches its manifest: "
            f"{', '.join(altered)}. Import it again",
            StepStatus.FAILED,
        )

    running = fw_probe.identify(chosen, release.version)
    if running.finding is fw_probe.Finding.RUNNING and not force:
        raise bench_api.Abandoned(
            f"{chosen} already runs {release.version}, so there is nothing to write",
            StepStatus.PASSED,
            Result(level=Level.OK, summary=running.sentence, fields=running.fields),
        )
    yield StepOutcome(
        StepStatus.PASSED,
        f"writing {release.version} to {chosen}: {running.sentence}",
        _result_for(running),
    )

    found = rom.detect(chosen)
    if not release.fits(found.chip):
        raise bench_api.Abandoned(
            f"{release.version} was built for {release.chip} and this board is "
            f"{found.description}. Refusing to write it",
            StepStatus.FAILED,
        )
    yield StepOutcome(
        StepStatus.PASSED,
        f"{found.description}, which is what {release.version} was built for",
        _ok("the image matches the silicon", **dict(found.fields)),
    )

    rom.erase(chosen, release.chip)
    yield StepOutcome(StepStatus.PASSED, "flash erased")

    for binary in release.binaries:
        rom.write(chosen, release, binary)
        yield StepOutcome(
            StepStatus.PASSED,
            f"wrote {binary.path.name} at {hex(binary.offset)}, {binary.size} bytes",
        )

    differing = rom.verify(chosen, release)
    if differing:
        raise bench_api.Abandoned(
            f"the board reads back different from what was written: "
            f"{', '.join(differing)}",
            StepStatus.FAILED,
        )
    yield StepOutcome(
        StepStatus.PASSED,
        f"all {len(release.binaries)} images read back as written",
    )

    settled = fw_probe.identify(chosen, release.version)
    yield StepOutcome(
        StepStatus.PASSED if settled else StepStatus.WARNED,
        settled.sentence,
        _result_for(settled),
    )


def _result_for(verdict: fw_probe.Verdict) -> Result:
    """Return a verdict as the panel behind the line that reports it."""
    return Result(
        level=Level.OK if verdict else Level.WARN,
        summary=verdict.sentence,
        fields=verdict.fields,
    )
