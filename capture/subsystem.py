from __future__ import annotations

from types import ModuleType
from typing import Any

from capture import capture
from capture.bench import (
    basics,
    calls,
    discover,
    events,
    filesystem,
    link,
    shots,
    survey,
)
from portable.ccapi import Camera
from portable.ccapi import LinkState as CameraLinkState
from shared.diagnostics import Diagnosable
from shared.subsystem import Level, Linked, LinkState, Readiness, Result


class Capture(Linked[str], Diagnosable):
    safe_state = "shutter released, not recording"
    target = link.HOST
    tests = (
        discover.Search,
        discover.WhetherItServes,
        basics.Health,
        basics.ReadAndWrite,
        shots.Captures,
        shots.FrameRate,
        shots.Records,
        filesystem.Files,
        events.HowLongAPollWaits,
        events.WatchForAWhile,
        survey.Everything,
        survey.RoundTripFloor,
    )
    commands = calls.COMMANDS

    def __init__(self, package: ModuleType, transport: Any = None) -> None:
        super().__init__(package)
        self._transport = transport

    def camera(self) -> Camera:
        return self.handle()

    def probe(self, target: str) -> Readiness:
        return link.can_connect(target)

    def _open(self, target: str) -> Camera:
        chosen = capture.settle(target)
        opened = Camera(capture.configured(chosen), self._transport)
        try:
            opened.connect()
        except Exception as exc:
            capture.log.warning("could not connect to {}: {}", chosen, exc)
            raise
        return opened

    def _close(self, handle: Camera) -> None:
        handle.disconnect()

    def _alive(self, handle: Camera) -> bool:
        return handle.link.state is CameraLinkState.UP

    def stop(self) -> None:
        found = self.camera()
        failures: list[str] = []
        try:
            found.shooting.release()
        except Exception as exc:
            failures.append(f"shutter: {type(exc).__name__}: {exc}")
        if found.movie.recording_by_us:
            try:
                found.movie.stop_recording()
            except Exception as exc:
                failures.append(f"recording: {type(exc).__name__}: {exc}")
        if failures:
            raise RuntimeError("; ".join(failures))

    def facts(self) -> Result | None:
        if self.link_state() is not LinkState.UP:
            return None
        found = self.camera()
        device = found.status.device()
        return Result(
            level=Level.OK,
            summary=f"{device.product_name} {device.serial_number}",
            fields=(
                ("model", device.product_name),
                ("serial", device.serial_number),
                ("firmware", device.firmware_version),
                ("versions", ", ".join(found.link.registry.versions)),
                ("endpoints", str(len(found.link.registry.features))),
            ),
        )
