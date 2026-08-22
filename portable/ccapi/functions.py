"""Camera-wide settings: power, clock, metadata names, certificates."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.link import GET, POST, PUT, Link

NAMES = {
    "copyright": Endpoint.REGISTEREDNAME_COPYRIGHT,
    "author": Endpoint.REGISTEREDNAME_AUTHOR,
    "owner": Endpoint.REGISTEREDNAME_OWNERNAME,
    "nickname": Endpoint.REGISTEREDNAME_NICKNAME,
    "artist": Endpoint.REGISTEREDNAME_ARTIST,
}

CAMERA_TIME = "%a, %d %b %Y %H:%M:%S"

log = logging.getLogger("ccapi.functions")


class Functions:
    def __init__(self, link: Link) -> None:
        self.link = link

    def auto_power_off(self) -> str:
        body = self.link.json(GET, Endpoint.AUTOPOWEROFF)
        return str(body.get("value", ""))

    def set_auto_power_off(self, value: str) -> None:
        self.link.json(PUT, Endpoint.AUTOPOWEROFF, payload={"value": value})

    @contextmanager
    def kept_awake(self, disabled: str = "disable") -> Generator[None]:
        found = self.auto_power_off()
        if found == disabled:
            yield
            return
        log.info("auto power-off was %r; holding it at %r", found, disabled)
        self.set_auto_power_off(disabled)
        try:
            yield
        finally:
            self.set_auto_power_off(found)

    def datetime(self) -> str:
        body = self.link.json(GET, Endpoint.DATETIME)
        return str(body.get("datetime", ""))

    def set_datetime(self, when: datetime | None = None, dst: bool = False) -> None:
        moment = when or datetime.now(timezone.utc).astimezone()
        stamp = f"{moment.strftime(CAMERA_TIME)} {moment.strftime('%z')}"
        self.link.json(PUT, Endpoint.DATETIME, payload={"datetime": stamp, "dst": dst})

    def registered(self, which: str) -> str:
        body = self.link.json(GET, NAMES[which])
        return str(body.get(_body_key(which), ""))

    def set_registered(self, which: str, value: str) -> None:
        self.link.json(PUT, NAMES[which], payload={_body_key(which): value})

    def clear_registered(self, which: str) -> None:
        from portable.ccapi.link import DELETE

        self.link.json(DELETE, NAMES[which])

    def beep(self) -> None:
        self.link.json(POST, Endpoint.BEEP, payload={"action": "on"})

    def display_off(self) -> None:
        self.link.json(POST, Endpoint.DISPLAYOFF, payload={"action": "on"})

    def viewfinder_off(self) -> None:
        self.link.json(POST, Endpoint.VIEWFINDEROFF, payload={"action": "on"})

    def cors_origin(self) -> str:
        body = self.link.json(GET, Endpoint.CORS_ORIGIN)
        return str(body.get("origin", ""))

    def set_cors_origin(self, origin: str) -> None:
        self.link.json(PUT, Endpoint.CORS_ORIGIN, payload={"origin": origin})

    def server_certificate_name(self) -> str:
        body = self.link.json(GET, Endpoint.SSL_SERVERCERT_COMMONNAME)
        return str(body.get("commonname", ""))

    def ca_certificate(self) -> bytes:
        return self.link.blob(Endpoint.SSL_CACERT)


def _body_key(which: str) -> str:
    return "ownername" if which == "owner" else which
