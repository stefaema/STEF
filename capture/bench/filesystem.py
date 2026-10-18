"""The card, end to end: what is mounted, what one frame does to it, and back out."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from capture.bench.shots import landed, swept
from portable.ccapi import ContentKind, PollWait, Setting
from portable.ccapi.vocabulary import NO_FILE
from shared.diagnostics import Failed, Test, end, step
from shared.subsystem import Level, Result, Table

if TYPE_CHECKING:
    from capture.subsystem import Capture

FRAME_BYTES = 8_000_000
REEL = 16_000
LISTED = 20


def megabytes(count: int) -> str:
    """Return a byte count as the number a person would say out loud."""
    return f"{count / 1_000_000:.1f} MB"


class Files(Test[Any]):
    """Follow one frame onto the card, off it, and back off again.

    Everything the scan does with storage in the order it does it, so a break
    is located rather than merely detected. The card is read before anything is
    written, so the counts either side of the release are comparable.

    The release is set to write both a raw and a jpeg, for two reasons. It is
    the only setting whose value and options are two-axis objects rather than
    flat strings, so it is the one that proves the client can talk about it at
    all; and the jpeg gives something showable, so the download step can put
    the frame on screen rather than assert a byte count at you.
    """

    sub: Capture

    @step("Cards")
    def cards(self) -> None:
        mounted = self.sub.camera().filesystem.storages()
        if not mounted:
            raise Failed("no media is mounted")
        self.report(
            f"{len(mounted)} mounted",
            Result(
                level=Level.OK,
                summary=f"{len(mounted)} card(s) mounted",
                note=f"'holds a reel' is {REEL} frames at {megabytes(FRAME_BYTES)} each",
                table=Table(
                    head=(
                        "Card",
                        "Access",
                        "Capacity",
                        "Free",
                        "Files",
                        "Holds a reel",
                    ),
                    rows=tuple(
                        (
                            one.name,
                            one.access.value,
                            megabytes(one.capacity),
                            megabytes(one.free),
                            str(one.file_count),
                            "yes" if one.holds(REEL, FRAME_BYTES) else "no",
                        )
                        for one in mounted
                    ),
                ),
            ),
        )

    @step("Contents")
    def contents(self) -> None:
        found = self.sub.camera()
        volumes = found.filesystem.volumes()
        directories: tuple[str, ...] = tuple(
            found.filesystem.directories(volumes[0]) if volumes else ()
        )
        self.directories = directories
        if not directories:
            raise Failed("this card has no directories to write into")
        self.before = before = found.filesystem.file_count
        self.report(
            f"{len(directories)} directory/ies, {before} file(s)",
            Result(
                level=Level.OK,
                summary=f"{len(volumes)} volume(s), {len(directories)} directory/ies",
                fields=(("files on the current card", str(before)),),
                table=Table(
                    head=("Directory",),
                    rows=tuple((one,) for one in directories),
                ),
            ),
        )

    @step("Write a frame", hazard="changes the image quality and releases the shutter")
    def write_a_frame(self) -> None:
        found = self.sub.camera()
        offered = found.settings.offers(Setting.STILLIMAGEQUALITY)
        self.was = was = found.settings.image_quality() if offered else None
        self.both = both = was is not None and was.offers_two
        if both and was is not None:
            found.settings.set_image_quality(
                next(one for one in was.raw_allowed if one != NO_FILE),
                next(one for one in was.jpeg_allowed if one != NO_FILE),
            )
        found.events.poll(PollWait.IMMEDIATELY)
        found.shooting.capture(af=False)
        self.announced = announced = landed(found)
        if not announced:
            raise Failed("nothing was announced after the release")
        self.report(
            f"{len(announced)} file(s) announced",
            Result(
                level=Level.OK,
                summary=f"one release announced {len(announced)} file(s)",
                note=(
                    None
                    if both
                    else "this body does not offer raw+jpeg, so one file is expected"
                ),
                table=Table(
                    head=("Announced",),
                    rows=tuple((one,) for one in announced),
                ),
            ),
        )

    @step("Find it without the event")
    def find_it_without_the_event(self) -> None:
        found = self.sub.camera()
        announced, before = self.announced, self.before
        walked = found.filesystem.files_in(self.directories[-1])
        after = found.filesystem.file_count
        agrees = all(one in walked for one in announced)
        grew = after - before
        shown = Result(
            level=Level.OK if agrees else Level.ERROR,
            summary=(
                "the walk and the event agree on what is on the card"
                if agrees
                else "the event announced a file the walk cannot find"
            ),
            fields=(
                ("announced", str(len(announced))),
                ("count grew by", str(grew)),
                ("listed in directory", str(len(walked))),
            ),
            table=Table(
                head=("File",),
                rows=tuple((one.rsplit("/", 1)[-1],) for one in walked[-LISTED:]),
            ),
        )
        said = f"{len(walked)} file(s) listed, count went {before} to {after}"
        if not agrees:
            raise Failed(said, shown)
        self.report(said, shown)

    @step("Download it")
    def download_it(self) -> None:
        found = self.sub.camera()
        announced = self.announced
        showable = _showable(found, announced)
        pulled = announced[0]
        started = time.monotonic()
        whole = found.filesystem.fetch(pulled, ContentKind.MAIN)
        took = time.monotonic() - started
        rate = len(whole) / took / 1_000_000 if took else 0.0
        hours = (REEL * len(whole) / (rate * 1_000_000) / 3600) if rate else 0.0
        self.measure("throughput", round(rate, 1), unit="MB/s")
        self.report(
            f"{megabytes(len(whole))} at {rate:.1f} MB/s",
            Result(
                level=Level.OK,
                summary=f"{megabytes(len(whole))} in {took:.2f} s, {rate:.1f} MB/s",
                note=(
                    f"a {REEL} frame reel would take {hours:.1f} h over this link, "
                    "which is why the card is the fast path"
                    if rate
                    else None
                ),
                image=showable,
                fields=(
                    ("file", pulled.rsplit("/", 1)[-1]),
                    ("full size", megabytes(len(whole))),
                    ("throughput", f"{rate:.1f} MB/s"),
                ),
            ),
        )

    @end("Delete it")
    def delete_it(self) -> None:
        found = self.sub.camera()
        was = getattr(self, "was", None)
        if getattr(self, "both", False) and was is not None:
            found.settings.set_image_quality(was.raw, was.jpeg)
        announced = getattr(self, "announced", ())
        if not hasattr(self, "before"):
            self.report("nothing was written")
            return
        before = self.before
        removed = swept(found, announced)
        settled = found.filesystem.file_count
        back = settled == before
        said = self.report if back and removed == len(announced) else self.warn
        said(
            f"{removed} removed, count back to {settled}",
            Result(
                level=Level.OK if back else Level.WARN,
                summary=(
                    "the card is as this found it"
                    if back
                    else f"the card holds {settled - before} more file(s) than it did"
                ),
                fields=(
                    ("before", str(before)),
                    ("after", str(settled)),
                    ("removed", f"{removed} of {len(announced)}"),
                ),
            ),
        )


def _showable(found: Any, announced: tuple[str, ...]) -> bytes | None:
    """Return a preview of the frame, or nothing if the camera will not render one.

    Asked of the jpeg where there is one. A body set to write raw only still
    answers, because `THUMBNAIL` is rendered by the camera rather than read out
    of the file, but a body that refuses is not worth failing the download over.
    """
    for path in announced:
        try:
            return found.filesystem.fetch(path, ContentKind.THUMBNAIL)
        except Exception:  # noqa: BLE001
            continue
    return None
