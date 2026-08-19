"""A camera that is not there, answering the way the reference says one would."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from portable.ccapi import RawReply

BASE = "/ccapi/ver110"


def endpoint(path: str, **methods: bool) -> dict[str, Any]:
    """Return one entry of the manifest, in the shape the camera publishes it."""
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
    "ver110": [endpoint("/ccapi/ver110/devicestatus/battery", get=True)],
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
    "/ccapi/ver100/devicestatus/temperature": {"status": "normal"},
    "/ccapi/ver100/devicestatus/currentdirectory": {"path": "sd/100CANON"},
    "/ccapi/ver100/shooting/settings/iso": {
        "value": "400",
        "ability": ["100", "200", "400", "800"],
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


class Camera:
    """One camera's worth of state, and the answers that follow from it."""

    def __init__(self) -> None:
        """Start with a card holding nothing and nothing on the event stream."""
        self.files: list[str] = []
        self.pending: list[str] = []
        self.shots = 0
        self.settings: dict[str, Any] = {}
        self.sent: list[tuple[str, str, Any]] = []

    # ── Answers that depend on what has happened ─────────────────────────────

    def storage(self) -> dict[str, Any]:
        """Return the card, whose free space and file count move as frames land."""
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

    def current(self) -> dict[str, Any]:
        """Return the one card frames are written to, which is the only one here."""
        return self.storage()["storagelist"][0]

    def shoot(self) -> dict[str, Any]:
        """Write one file and remember it as news nobody has been told yet."""
        self.shots += 1
        made = f"/ccapi/ver100/contents/sd/100CANON/IMG_{self.shots:04d}.JPG"
        self.files.append(made)
        self.pending.append(made)
        return {}

    def polled(self) -> dict[str, Any]:
        """Return what changed, which is only ever said once."""
        added, self.pending = self.pending, []
        return {"addedcontents": added} if added else {}

    def setting(self, feature: str) -> dict[str, Any]:
        """Return one setting, as this camera has it now."""
        shipped = BODIES.get(f"/ccapi/ver100/{feature}", {})
        value = self.settings.get(feature, shipped.get("value"))
        return {"value": value, "ability": shipped.get("ability", [])}


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
        path = url.split("8080", 1)[-1].split("?", 1)[0]
        self.camera.sent.append((method, path, payload))
        body = self._body(method, path, payload)
        if body is None:
            return RawReply(
                status=404, body=json.dumps({"message": "URL not found"}).encode()
            )
        return RawReply(status=200, body=json.dumps(body).encode())

    def _body(self, method: str, path: str, payload: Any) -> Any:
        """Return what this camera says to one request, or None where it has nothing."""
        feature = path.split("/ccapi/ver100/", 1)[-1].split("/ccapi/ver110/", 1)[-1]
        if path == "/ccapi/ver100/devicestatus/storage":
            return self.camera.storage()
        if path == "/ccapi/ver100/devicestatus/currentstorage":
            return self.camera.current()
        if path == "/ccapi/ver100/event/polling":
            return self.camera.polled()
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
        """Answer the filesystem, which is a list until it is a deletion."""
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
        return {"path": list(self.camera.files)}

    def close(self) -> None:
        """Nothing is held, so there is nothing to let go of."""
