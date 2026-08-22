"""In-memory CCAPI camera for tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
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
    """Return one manifest entry: a path plus True for each method named."""
    return {"path": f"{ROOT}/{feature}", **{name: True for name in methods}}


MANIFEST = {
    VERSION: [
        endpoint("devicestatus/storage", get=True),
        endpoint("devicestatus/currentstorage", get=True),
        endpoint("devicestatus/currentdirectory", get=True),
        endpoint("contents", get=True, delete=True),
        endpoint("event/monitoring", get=True, delete=True),
        endpoint("shooting/liveview", post=True),
        endpoint("shooting/liveview/scrolldetail", get=True),
        endpoint("shooting/liveview/multipart", get=True),
        endpoint("shooting/settings/iso", get=True, put=True),
        endpoint("shooting/settings/stillimagequality", get=True, put=True),
        endpoint("shooting/control/moviemode", get=True, post=True),
        endpoint("shooting/control/recbutton", post=True),
    ]
}


class Camera:
    """Fake camera state and the responses derived from it."""

    def __init__(self, mode_lag: int = 0) -> None:
        self.files = ["IMG_0001.JPG", "IMG_0002.CR3", "IMG_0003.JPG"]
        self.quality = {"raw": "none", "jpeg": "large_fine"}
        self.in_movie = False
        self.recording = False
        self.mode_lag = mode_lag
        self.monitoring_open = False
        self.live_view_open = False
        self.asked: list[tuple[str, str]] = []
        self._stale = 0

    def storages(self) -> dict[str, Any]:
        """Return the devicestatus/storage response body."""
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
        """Return the devicestatus/currentstorage response body."""
        return {"name": CARD, "path": f"{ROOT}/contents/{CARD}"}

    def contents(self, tail: str, page: str = "") -> dict[str, Any] | None:
        """Return the contents listing for `tail`, or None if the path is unknown."""
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

    def still_image_quality(self) -> dict[str, Any]:
        """Return the stillimagequality body, whose value and ability are objects."""
        return {
            "value": dict(self.quality),
            "ability": {"raw": list(RAW_ABILITY), "jpeg": list(JPEG_ABILITY)},
        }

    def movie_mode(self) -> dict[str, Any]:
        """Return the mode, reporting the old one for the next `mode_lag` reads."""
        settled = self.in_movie
        if self._stale > 0:
            self._stale -= 1
            settled = not self.in_movie
        return {"status": "on" if settled else "off"}

    def watch(self, method: str) -> dict[str, Any] | Refused:
        """Open or close the monitoring stream; a second open is refused."""
        if method == "DELETE":
            self.monitoring_open = False
            return {}
        if self.monitoring_open:
            return Refused("Already started")
        self.monitoring_open = True
        return {}

    def size_live_view(self, size: str) -> dict[str, Any]:
        """Apply live view settings; `off` also ends the stream."""
        if size == "off":
            self.live_view_open = False
        return {}

    def open_live_view_stream(self) -> dict[str, Any] | Refused:
        """Start the live view stream; a second start is refused."""
        if self.live_view_open:
            return Refused("Already started")
        self.live_view_open = True
        return {}

    def change_mode(self, action: str) -> dict[str, Any]:
        """Set the mode and begin the run of stale reads."""
        self.in_movie = action == "on"
        self._stale = self.mode_lag
        return {}


@dataclass(frozen=True, slots=True)
class Refused:
    """A 503 response with a refusal message."""

    message: str


class Transport:
    """Transport that answers from a `Camera` instead of over HTTP."""

    def __init__(self, camera: Camera | None = None) -> None:
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
        """Return the response to one request and record it."""
        path, _, query = url.split("8080", 1)[-1].partition("?")
        self.camera.asked.append((method, path))
        body = self._body(method, path, payload, dict(parse_qsl(query)))
        if body is None:
            return RawReply(
                status=404, body=json.dumps({"message": "URL not found"}).encode()
            )
        if isinstance(body, Refused):
            return RawReply(
                status=503, body=json.dumps({"message": body.message}).encode()
            )
        return RawReply(status=200, body=json.dumps(body).encode())

    def _body(self, method: str, path: str, payload: Any, query: dict[str, str]) -> Any:
        """Return the response body for one request, or None if the path is unknown."""
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
        if feature == "event/monitoring":
            return self.camera.watch(method)
        if feature == "shooting/liveview":
            return self.camera.size_live_view((payload or {}).get("liveviewsize", ""))
        if feature == "shooting/liveview/scrolldetail":
            return self.camera.open_live_view_stream()
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
        """Do nothing; this transport holds no connection."""


def connected(camera: Camera | None = None):
    """Return a connected client and the fake camera behind it."""
    from portable.ccapi import Camera as Client

    transport = Transport(camera)
    client = Client(CameraConfig(host="10.0.0.2"), transport)
    client.connect()
    return client, transport.camera
