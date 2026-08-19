from __future__ import annotations

import enum
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.link import GET, POST, Link


class ShutterAction(enum.StrEnum):
    RELEASE = "release"
    HALF_PRESS = "half_press"
    FULL_PRESS = "full_press"


class FocusStep(enum.StrEnum):
    NEAR_1 = "near1"
    NEAR_2 = "near2"
    NEAR_3 = "near3"
    FAR_1 = "far1"
    FAR_2 = "far2"
    FAR_3 = "far3"


class ZoomAction(enum.StrEnum):
    TELE_1 = "tele1"
    TELE_2 = "tele2"
    WIDE_1 = "wide1"
    WIDE_2 = "wide2"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class FlickerResult:
    detected: bool
    recommended_tv: str | None = None


class HeldButton:
    def __init__(self, shooting: Shooting, af: bool) -> None:
        self._shooting = shooting
        self._af = af
        self._down = False

    @property
    def fully_down(self) -> bool:
        return self._down

    def press(self) -> None:
        if self._down:
            self._shooting.act(ShutterAction.HALF_PRESS, self._af)
        self._shooting.act(ShutterAction.FULL_PRESS, self._af)
        self._down = True

    def let_up(self) -> None:
        self._shooting.act(ShutterAction.HALF_PRESS, self._af)
        self._down = False


class Shooting:
    def __init__(self, link: Link) -> None:
        self.link = link

    # ── One frame ────────────────────────────────────────────────────────────

    def capture(self, af: bool = False) -> None:
        self.link.json(POST, Endpoint.SHUTTERBUTTON, payload={"af": af})

    # ── The button, held ─────────────────────────────────────────────────────

    def act(self, action: ShutterAction, af: bool = False) -> None:
        self.link.json(
            POST,
            Endpoint.SHUTTERBUTTON_MANUAL,
            payload={"action": action.value, "af": af},
        )

    def release(self) -> None:
        self.act(ShutterAction.RELEASE)

    @contextmanager
    def held(self, af: bool = False) -> Generator[HeldButton]:
        self.act(ShutterAction.HALF_PRESS, af)
        try:
            yield HeldButton(self, af)
        finally:
            self.release()

    # ── Focus ────────────────────────────────────────────────────────────────

    def autofocus(self, start: bool = True) -> None:
        self.link.json(
            POST, Endpoint.AF, payload={"action": "start" if start else "stop"}
        )

    def drive_focus(self, step: FocusStep) -> None:
        self.link.json(POST, Endpoint.DRIVEFOCUS, payload={"action": step.value})

    # ── Zoom ─────────────────────────────────────────────────────────────────

    def zoom(self, action: ZoomAction) -> None:
        self.link.json(POST, Endpoint.ZOOM, payload={"action": action.value})

    # ── Flicker ──────────────────────────────────────────────────────────────

    def detect_flicker(self) -> FlickerResult:
        body = self.link.json(POST, Endpoint.FLICKERDETECTION, payload={"action": "on"})
        return FlickerResult(detected=bool(body.get("detect")))

    def detect_hf_flicker(self, apply_result: bool = False) -> FlickerResult:
        body = self.link.json(
            POST,
            Endpoint.HFFLICKERDETECTION,
            payload={"action": "on", "apply_result": apply_result},
        )
        return FlickerResult(
            detected=bool(body.get("detect")),
            recommended_tv=body.get("tv"),
        )

    def recommended_flicker_tv(self) -> str:
        body = self.link.json(GET, Endpoint.HFFLICKERTV)
        return str(body.get("value", ""))

    # ── Overriding the physical dial ─────────────────────────────────────────

    def dial_ignored_now(self) -> bool:
        body = self.link.json(GET, Endpoint.IGNORESHOOTINGMODEDIALMODE)
        return str(body.get("status", "")) == "on"

    @contextmanager
    def dial_ignored(self) -> Generator[None]:
        if self.dial_ignored_now():
            yield
            return
        self._set_dial_ignored(True)
        try:
            yield
        finally:
            self._set_dial_ignored(False)

    def _set_dial_ignored(self, ignored: bool) -> None:
        self.link.json(
            POST,
            Endpoint.IGNORESHOOTINGMODEDIALMODE,
            payload={"action": "on" if ignored else "off"},
        )
