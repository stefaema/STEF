"""Everything this camera will say about itself, written down while we have it."""

import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from portable.ccapi import STREAMED, Endpoint, Methods, Setting
from shared.diagnostics import Test, end, step
from shared.subsystem import Level, Result, Table, boolean, integer

if TYPE_CHECKING:
    from capture.subsystem import Capture

PREFIX = "stef-survey-"
RESPONSES = "responses.json"
SETTINGS = "settings.json"
ABOUT = "about.json"
UNNAMED = "unnamed.json"

NAMED = {str(one) for one in Endpoint} | {str(one) for one in Setting}


def somewhere() -> Path:
    """Return a fresh directory to write into, which nothing here promises to keep."""
    return Path(tempfile.mkdtemp(prefix=PREFIX))


def written(where: Path, name: str, body: Any) -> int:
    """Write one file and say how big it came out."""
    target = where / name
    target.write_text(json.dumps(body, indent=2, sort_keys=True))
    return target.stat().st_size


class Everything(Test[Any]):
    """Ask this camera every question it will answer and write the answers down.

    Verbatim, never parsed: the point is to have something our own reading can
    be checked against, and a stored interpretation would carry the same
    misunderstanding as the code that made it.
    """

    sub: Capture
    inputs = (
        boolean(
            "keep",
            hint="Leave the files on disk. Off deletes them once you have looked.",
        ),
    )

    @step("About")
    def about(self) -> None:
        found = self.sub.camera()
        self.where = somewhere()
        self.total = 0
        self.refused: list[tuple[str, ...]] = []
        device = found.status.device()
        about = {
            "model": device.product_name,
            "serial": device.serial_number,
            "firmware": device.firmware_version,
            "versions": list(found.link.registry.versions),
            "declined": list(found.link.registry.offered_beyond_accepted),
            "taken": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.total += written(self.where, ABOUT, about)
        self.report(f"{device.product_name} {device.serial_number}")

    @step("Manifest")
    def manifest(self) -> None:
        found = self.sub.camera()
        self.responses: dict[str, Any] = {"/ccapi": found.link.manifest}
        self.report(f"{len(found.link.registry.features)} endpoints")

    @step("Read everything")
    def read_everything(self) -> None:
        found = self.sub.camera()
        for feature in found.link.registry.features:
            self.checkpoint()
            if Methods.GET not in found.link.registry.methods_for(feature):
                continue
            if feature in STREAMED:
                self.refused.append(
                    (feature, "a stream, which a plain GET would hold open")
                )
                continue
            try:
                self.responses[feature] = found.link.json("GET", feature)
            except Exception as exc:  # noqa: BLE001
                self.refused.append((feature, f"{type(exc).__name__}: {exc}"))
        self.total += written(self.where, RESPONSES, self.responses)
        self.report(f"{len(self.responses)} answered, {len(self.refused)} refused")

    @step("Settings")
    def settings(self) -> None:
        found = self.sub.camera()
        said: dict[str, Any] = {}
        for setting in Setting:
            if not found.settings.offers(setting):
                continue
            try:
                value = found.settings.get(setting)
                said[str(setting)] = {
                    "value": value.value,
                    "allowed": list(value.allowed),
                }
            except Exception as exc:  # noqa: BLE001
                self.refused.append((str(setting), f"{type(exc).__name__}: {exc}"))
        self.total += written(self.where, SETTINGS, said)
        self.report(f"{len(said)} settings read")

    @step("Unnamed")
    def unnamed(self) -> None:
        found = self.sub.camera()
        keep = bool(self.values.get("keep"))
        unnamed = found.link.registry.unnamed(NAMED)
        self.total += written(self.where, UNNAMED, list(unnamed))
        summary = (
            f"{len(unnamed)} endpoint(s) this build has no name for"
            if unnamed
            else "every endpoint offered has a name here"
        )
        said = self.warn if unnamed else self.report
        said(
            summary,
            Result(
                level=Level.WARN if unnamed else Level.OK,
                summary=summary,
                note=(
                    f"written to {self.where}"
                    if keep
                    else "deleted; tick 'keep' to hold on to it"
                ),
                fields=(
                    ("bytes", str(self.total)),
                    ("refused", str(len(self.refused))),
                ),
                table=Table(head=("Endpoint",), rows=tuple((one,) for one in unnamed))
                if unnamed
                else None,
            ),
        )

    @end("Tidy up")
    def tidy_up(self) -> None:
        where = getattr(self, "where", None)
        if where is None or self.values.get("keep"):
            self.report(f"kept in {where}" if where else "nothing was written")
            return
        shutil.rmtree(where, ignore_errors=True)
        self.report("deleted")


class RoundTripFloor(Test[Any]):
    """Time the cheapest call there is, repeatedly.

    Every other number this bench reports is measured against this one. A fetch
    that takes 400ms means nothing until you know whether an empty round trip
    takes 4ms or 200.
    """

    sub: Capture
    inputs = (integer("samples", min=3, max=500),)

    @step("Time it")
    def time_it(self) -> None:
        found = self.sub.camera()
        samples = int(self.values.get("samples", 50))
        taken: list[float] = []
        for _ in range(samples):
            started = time.monotonic()
            found.status.battery()
            taken.append((time.monotonic() - started) * 1000)
        taken.sort()
        middle = taken[len(taken) // 2]
        self.measure("median", round(middle), unit="ms")
        self.report(
            f"{middle:.0f} ms median",
            Result(
                level=Level.OK,
                summary=f"{samples} round trips, {middle:.0f} ms median",
                fields=(
                    ("fastest", f"{taken[0]:.0f} ms"),
                    ("median", f"{middle:.0f} ms"),
                    ("slowest", f"{taken[-1]:.0f} ms"),
                ),
            ),
        )
