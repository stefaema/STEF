"""In-memory CCAPI camera for tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs

from portable.ccapi import RawReply

BASE = "/ccapi/ver110"


def endpoint(path: str, **methods: bool) -> dict[str, Any]:
    """Return one manifest entry: a path plus True for each method named."""
    return {"path": path, **{name: True for name in methods}}


MANIFEST = {
    "ver100": [
        endpoint("/ccapi/ver100/deviceinformation", get=True),
        endpoint("/ccapi/ver100/devicestatus/battery", get=True),
        endpoint("/ccapi/ver100/devicestatus/temperature", get=True),
        endpoint("/ccapi/ver100/devicestatus/storage", get=True),
        endpoint("/ccapi/ver100/devicestatus/currentstorage", get=True),
        endpoint("/ccapi/ver100/devicestatus/currentdirectory", get=True),
        endpoint("/ccapi/ver100/contents", get=True, delete=True),
        endpoint("/ccapi/ver100/event/polling", get=True, delete=True),
        endpoint("/ccapi/ver100/shooting/control/shutterbutton", post=True),
        endpoint("/ccapi/ver100/shooting/control/shutterbutton/manual", post=True),
        endpoint("/ccapi/ver100/shooting/settings/iso", get=True, put=True),
        endpoint("/ccapi/ver100/shooting/settings/drive", get=True, put=True),
        endpoint("/ccapi/ver100/functions/autopoweroff", get=True, put=True),
    ],
    "ver110": [
        endpoint("/ccapi/ver110/devicestatus/battery", get=True),
        endpoint(
            "/ccapi/ver110/shooting/settings/stillimagequality", get=True, put=True
        ),
    ],
    "ver140": [endpoint("/ccapi/ver140/devicestatus/battery", get=True)],
}

BODIES: dict[str, Any] = {
    "/ccapi": MANIFEST,
    "/ccapi/ver100/deviceinformation": {
        "manufacturer": "Canon.Inc",
        "productname": "Canon EOS R50",
        "guid": "0" * 32,
        "serialnumber": "123456789012",
        "macaddress": "a1:b2:c3:d4:e5:f6",
        "firmwareversion": "1.1.0",
    },
    "/ccapi/ver110/devicestatus/battery": {
        "name": "LP-E17",
        "kind": "battery",
        "level": "full",
        "quality": "good",
    },
    "/ccapi/ver140/devicestatus/battery": {
        "name": "LP-E17",
        "kind": "battery",
        "level": "full",
        "quality": "good",
    },
    "/ccapi/ver100/devicestatus/temperature": {"status": "normal"},
    "/ccapi/ver100/devicestatus/currentdirectory": {"path": "sd/100CANON"},
    "/ccapi/ver100/shooting/settings/iso": {
        "value": "400",
        "ability": ["100", "200", "400", "800"],
    },
    "/ccapi/ver110/shooting/settings/stillimagequality": {
        "value": {"raw": "none", "jpeg": "small"},
        "ability": {
            "raw": ["none", "raw", "craw"],
            "jpeg": [
                "none",
                "large_fine",
                "large_normal",
                "medium_fine",
                "medium_normal",
                "small",
            ],
        },
    },
    "/ccapi/ver100/shooting/settings/drive": {
        "value": "single",
        "ability": ["single", "highspeed", "lowspeed"],
    },
    "/ccapi/ver100/functions/autopoweroff": {
        "value": "1min",
        "ability": ["disable", "1min", "5min"],
    },
}


# Enough of a jpeg that anything sniffing magic bytes agrees what it is.
JPEG = b"\xff\xd8\xff\xe0"

# How many bytes each rendering costs, so the sizes are told apart in a test.
RENDERED = {"thumbnail": 970, "display": 100_000, "main": 16_167_276}


class Camera:
    """Fake camera state and the responses derived from it."""

    def __init__(self) -> None:
        self.files: list[str] = []
        self.pending: list[str] = []
        self.shots = 0
        self.settings: dict[str, Any] = {}
        self.sent: list[tuple[str, str, Any]] = []

    def storage(self) -> dict[str, Any]:
        """Return the devicestatus/storage response body."""
        return {
            "storagelist": [
                {
                    "name": "sd",
                    "url": "http://10.0.0.2:8080/ccapi/ver100/contents/sd",
                    "accesscapability": "readwrite",
                    "maxsize": 128_000_000_000,
                    "spacesize": 128_000_000_000 - len(self.files) * 8_000_000,
                    "contentsnumber": len(self.files),
                }
            ]
        }

    def current_storage(self) -> dict[str, Any]:
        """Return the devicestatus/currentstorage body, which has no counts."""
        return {"name": "sd", "path": "/ccapi/ver100/contents/sd"}

    def shoot(self) -> dict[str, Any]:
        """Add one file to the card and queue an event for it."""
        self.shots += 1
        made = f"/ccapi/ver100/contents/sd/100CANON/IMG_{self.shots:04d}.JPG"
        self.files.append(made)
        self.pending.append(made)
        return {}

    def drain_events(self) -> dict[str, Any]:
        """Return the event/polling body and clear the queue."""
        added, self.pending = self.pending, []
        return {"addedcontents": added} if added else {}

    def content(self, path: str, kind: str) -> bytes | None:
        """Return the bytes of one file, or nothing if this is not a fetch of one.

        The camera renders `thumbnail` and `display` itself rather than reading
        them out of the file, so it answers for a raw original too. Both are
        jpeg whatever the original is.
        """
        if kind not in RENDERED or path not in self.files:
            return None
        return JPEG + bytes(RENDERED[kind])

    def setting(self, feature: str) -> dict[str, Any]:
        """Return one setting: its current value and accepted values."""
        shipped = next(
            (body for path, body in BODIES.items() if path.endswith(f"/{feature}")), {}
        )
        value = self.settings.get(feature, shipped.get("value"))
        return {"value": value, "ability": shipped.get("ability", [])}


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
        whole = url.split("8080", 1)[-1]
        path, _, query = whole.partition("?")
        self.camera.sent.append((method, path, payload))
        if method == "GET":
            blob = self.camera.content(path, parse_qs(query).get("kind", [""])[0])
            if blob is not None:
                return RawReply(status=200, body=blob)
        body = self._body(method, path, payload)
        if body is None:
            return RawReply(
                status=404, body=json.dumps({"message": "URL not found"}).encode()
            )
        return RawReply(status=200, body=json.dumps(body).encode())

    def _body(self, method: str, path: str, payload: Any) -> Any:
        """Return the response body for one request, or None if the path is unknown."""
        feature = path.split("/ccapi/ver100/", 1)[-1].split("/ccapi/ver110/", 1)[-1]
        if path == "/ccapi/ver100/devicestatus/storage":
            return self.camera.storage()
        if path == "/ccapi/ver100/devicestatus/currentstorage":
            return self.camera.current_storage()
        if path == "/ccapi/ver100/event/polling":
            return self.camera.drain_events()
        if path.endswith("/shutterbutton"):
            return self.camera.shoot()
        if path.endswith("/shutterbutton/manual"):
            action = (payload or {}).get("action")
            return self.camera.shoot() if action == "full_press" else {}
        if feature.startswith(("shooting/settings/", "functions/")):
            if method == "PUT":
                self.camera.settings[feature] = (payload or {}).get("value")
                return {}
            return self.camera.setting(feature)
        if path.startswith("/ccapi/ver100/contents"):
            return self._contents(method, path)
        return BODIES.get(path)

    def _contents(self, method: str, path: str) -> Any:
        """Return a contents listing, or delete the file at the path."""
        if method == "DELETE":
            target = path
            self.camera.files = [
                one
                for one in self.camera.files
                if not target.endswith(one.split("/contents/")[-1])
            ]
            return {}
        tail = path.split("/contents", 1)[-1].strip("/")
        if not tail:
            return {"path": ["/ccapi/ver100/contents/sd"]}
        if tail == "sd":
            return {"path": ["/ccapi/ver100/contents/sd/100CANON"]}
        if tail == "sd/100CANON":
            return {"path": list(self.camera.files)}
        return None

    def close(self) -> None:
        """Do nothing; this transport holds no connection."""
