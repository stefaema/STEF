"""A camera that is not there, answering the way the reference says one would.

Deliberately no more generous than a real body: `currentstorage` names the card
and nothing else, and a path it never published comes back 404. A fake that
answers what a caller wishes it had asked hides exactly the bugs worth catching.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl

from portable.ccapi import CameraConfig, RawReply

VERSION = "ver140"
ROOT = f"/ccapi/{VERSION}"
CARD = "card1"
FOLDER = "100CANON"

RAW_ABILITY = ("none", "raw", "craw")
JPEG_ABILITY = ("none", "large_fine", "large_normal", "small")


def endpoint(feature: str, **methods: bool) -> dict[str, Any]:
    """Return one manifest entry, in the shape the camera publishes it."""
    return {"path": f"{ROOT}/{feature}", **{name: True for name in methods}}


MANIFEST = {
    VERSION: [
        endpoint("devicestatus/storage", get=True),
        endpoint("devicestatus/currentstorage", get=True),
        endpoint("devicestatus/currentdirectory", get=True),
        endpoint("contents", get=True, delete=True),
        endpoint("event/monitoring", get=True, delete=True),
        endpoint("shooting/liveview/multipart", get=True),
        endpoint("shooting/settings/iso", get=True, put=True),
        endpoint("shooting/settings/stillimagequality", get=True, put=True),
        endpoint("shooting/control/moviemode", get=True, post=True),
        endpoint("shooting/control/recbutton", post=True),
    ]
}


class Camera:
    """One camera's worth of state, and the answers that follow from it."""

    def __init__(self, mode_lag: int = 0) -> None:
        """Take how many reads answer staleley after a mode change, which is the race."""
        self.files = ["IMG_0001.JPG", "IMG_0002.CR3", "IMG_0003.JPG"]
        self.quality = {"raw": "none", "jpeg": "large_fine"}
        self.in_movie = False
        self.recording = False
        self.mode_lag = mode_lag
        self.asked: list[tuple[str, str]] = []
        self._stale = 0

    # ── The card ─────────────────────────────────────────────────────────────

    def storages(self) -> dict[str, Any]:
        """Return every card, which is where the numbers live."""
        return {
            "storagelist": [
                {
                    "name": CARD,
                    "url": f"http://10.0.0.2:8080{ROOT}/contents/{CARD}",
                    "accesscapability": "readwrite",
                    "maxsize": 128_000_000_000,
                    "spacesize": 96_000_000_000,
                    "contentsnumber": len(self.files),
                }
            ]
        }

    def current_storage(self) -> dict[str, Any]:
        """Name the card being written to. Two fields, as the reference has it."""
        return {"name": CARD, "path": f"{ROOT}/contents/{CARD}"}

    def contents(self, tail: str, page: str = "") -> dict[str, Any] | None:
        """Return one listing, or nothing for a path this camera never published.

        A page past the end is empty, which is what tells a walk to stop.
        """
        if not tail:
            return {"path": [f"{ROOT}/contents/{CARD}"]}
        if tail == CARD:
            return {"path": [f"{ROOT}/contents/{CARD}/{FOLDER}"]}
        if tail != f"{CARD}/{FOLDER}":
            return None
        if page and int(page) > 1:
            return {"path": [], "contentsnumber": 0}
        return {
            "path": [f"{ROOT}/contents/{CARD}/{FOLDER}/{one}" for one in self.files],
            "contentsnumber": len(self.files),
        }

    # ── The one setting with two axes ────────────────────────────────────────

    def still_image_quality(self) -> dict[str, Any]:
        """Return quality the way the reference documents its one exception."""
        return {
            "value": dict(self.quality),
            "ability": {"raw": list(RAW_ABILITY), "jpeg": list(JPEG_ABILITY)},
        }

    # ── The mode, which does not arrive when the acknowledgement does ────────

    def movie_mode(self) -> dict[str, Any]:
        """Return the mode, answering with the old one while the change is settling."""
        settled = self.in_movie
        if self._stale > 0:
            self._stale -= 1
            settled = not self.in_movie
        return {"status": "on" if settled else "off"}

    def change_mode(self, action: str) -> dict[str, Any]:
        """Acknowledge a mode change now and arrive at it later."""
        self.in_movie = action == "on"
        self._stale = self.mode_lag
        return {}


class Transport:
    """The seam, answering out of a `Camera` instead of off a network."""

    def __init__(self, camera: Camera | None = None) -> None:
        """Take the camera to answer for, making an untouched one when given none."""
        self.camera = camera or Camera()

    def send(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
        stream: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> RawReply:
        """Answer one request, recording it so a test can say what was asked."""
        path, _, query = url.split("8080", 1)[-1].partition("?")
        self.camera.asked.append((method, path))
        body = self._body(method, path, payload, dict(parse_qsl(query)))
        if body is None:
            return RawReply(
                status=404, body=json.dumps({"message": "URL not found"}).encode()
            )
        return RawReply(status=200, body=json.dumps(body).encode())

    def _body(self, method: str, path: str, payload: Any, query: dict[str, str]) -> Any:
        """Return what this camera says to one request, or None where it has nothing."""
        if path == "/ccapi":
            return MANIFEST
        feature = path.removeprefix(f"{ROOT}/")
        if feature == "devicestatus/storage":
            return self.camera.storages()
        if feature == "devicestatus/currentstorage":
            return self.camera.current_storage()
        if feature == "devicestatus/currentdirectory":
            return {"path": f"{ROOT}/contents/{CARD}/{FOLDER}"}
        if feature == "shooting/settings/stillimagequality":
            if method == "PUT":
                self.camera.quality = dict((payload or {}).get("value") or {})
                return {}
            return self.camera.still_image_quality()
        if feature == "shooting/settings/iso":
            return {"value": "400", "ability": ["100", "200", "400"]}
        if feature == "shooting/control/moviemode":
            if method == "POST":
                return self.camera.change_mode((payload or {}).get("action", ""))
            return self.camera.movie_mode()
        if feature == "shooting/control/recbutton":
            self.camera.recording = (payload or {}).get("action") == "start"
            return {}
        if feature == "contents" or feature.startswith("contents/"):
            if method == "DELETE":
                return {}
            return self.camera.contents(
                feature.removeprefix("contents").strip("/"), query.get("page", "")
            )
        return None

    def close(self) -> None:
        """Nothing is held, so there is nothing to let go of."""


def connected(camera: Camera | None = None):
    """Return a camera object already linked to a fake, and the fake behind it."""
    from portable.ccapi import Camera as Client

    transport = Transport(camera)
    client = Client(CameraConfig(host="10.0.0.2"), transport)
    client.connect()
    return client, transport.camera
