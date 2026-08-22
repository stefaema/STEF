"""Who is on the network, and whether they will answer, without disturbing them."""

from __future__ import annotations

import enum
import socket
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from urllib.parse import urlparse

from portable.ccapi import (
    Camera,
    CameraConfig,
    CcapiError,
    NotActivatedError,
    UnacceptableVersionError,
    UnreachableError,
)
from shared import logs

GROUP = "239.255.255.250"
PORT = 1900
SERVICE = "urn:schemas-canon-com:service:ICPO-CameraControlAPIService:1"
UPNP = "{urn:schemas-upnp-org:device-1-0}"
WAIT = 2.0
HOP = 2

log = logs.component("capture.probe")


class NoCameraError(CcapiError):
    """Nothing to connect to, or too many things to choose between."""


class NotConnected(CcapiError):
    """Asked for the camera while none was open."""


@dataclass(frozen=True, slots=True)
class Found:
    """One camera a discovery search turned up, and what it says about itself."""

    host: str
    port: int
    model: str
    serial: str
    serving: bool

    @property
    def label(self) -> str:
        """Return what to call it in a list, which is what it is plus what it admits."""
        said = self.model or "camera"
        if self.serial:
            said = f"{said} {self.serial[-6:]}"
        return (
            f"{self.host} ({said})"
            if self.serving
            else f"{self.host} ({said}, CCAPI off)"
        )


# ── Asking the network ───────────────────────────────────────────────────────


def search(wait: float = WAIT) -> tuple[Found, ...]:
    """Return every camera that answers a discovery search, in address order.

    Multicast, so this reaches one subnet and no further, and a switch that
    drops it makes a present camera invisible. Silence is not an answer.
    """
    found: dict[str, Found] = {}
    for location in _locations(wait):
        described = describe(location)
        if described is not None:
            found[described.host] = described
    return tuple(sorted(found.values(), key=lambda one: one.host))


def _locations(wait: float) -> tuple[str, ...]:
    """Return the description URL every camera answered a search with."""
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {GROUP}:{PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {int(wait)}\r\n"
        f"ST: {SERVICE}\r\n\r\n"
    ).encode()
    seen: list[str] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, HOP)
        sock.settimeout(wait)
        try:
            sock.sendto(request, (GROUP, PORT))
        except OSError as exc:
            log.debug("no discovery search went out: {}", exc)
            return ()
        while True:
            try:
                payload, _ = sock.recvfrom(4096)
            except (TimeoutError, OSError):
                break
            location = _header(payload.decode("utf-8", "replace"), "location")
            if location and location not in seen:
                seen.append(location)
    return tuple(seen)


def _header(response: str, name: str) -> str:
    """Return one header out of an SSDP reply, matched however it was capitalised."""
    for line in response.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == name:
            return value.strip()
    return ""


def describe(location: str) -> Found | None:
    """Return what one camera's description says, or None when it will not answer."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(location, timeout=WAIT) as reply:
            document = reply.read()
    except (urllib.error.URLError, OSError) as exc:
        log.debug("{} did not describe itself: {}", location, exc)
        return None
    return _read(document, location)


def _read(document: bytes, location: str) -> Found | None:
    """Return a device description as the fields a list needs."""
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError:
        return None
    device = root.find(f"{UPNP}device")
    if device is None:
        return None
    access = _text(device, "X_accessURL")
    parsed = urlparse(access) if access else urlparse(location)
    if not parsed.hostname:
        return None
    return Found(
        host=parsed.hostname,
        port=parsed.port or 8080,
        model=_text(device, f"{UPNP}modelName") or _text(device, f"{UPNP}friendlyName"),
        serial=_text(device, f"{UPNP}serialNumber"),
        serving=_text(device, "X_onService") == "1",
    )


def _text(device: ElementTree.Element, tag: str) -> str:
    """Return one tag's text, searched by both its plain and namespaced name."""
    for name in (tag, f"{UPNP}{tag}"):
        node = device.find(name)
        if node is not None and node.text:
            return node.text.strip()
    return ""


# ── Whether it is worth connecting to ────────────────────────────────────────


class Finding(enum.Enum):
    """What asking settled, ordered by how much of the camera answered."""

    SERVING = "serving"
    INCOMPATIBLE = "incompatible"
    NOT_ACTIVATED = "not_activated"
    REFUSED = "refused"
    UNREACHABLE = "unreachable"

    @property
    def ok(self) -> bool:
        """Whether this is a camera the bench can go on to use."""
        return self is Finding.SERVING


@dataclass(frozen=True, slots=True)
class Verdict:
    """What one address turned out to be, in the words an operator reads."""

    finding: Finding
    host: str
    sentence: str

    def __bool__(self) -> bool:
        """Return whether the camera is usable, so a verdict reads like a check."""
        return self.finding.ok


def identify(config: CameraConfig) -> Verdict:
    """Return whether this address will serve us, and what is there when it will not.

    Asked rather than remembered. A remembered answer goes stale the moment
    someone picks up the camera, and the refusal an operator can act on is the
    one that names what it found.
    """
    probing = Camera(config)
    try:
        probing.connect()
    except NotActivatedError:
        return Verdict(
            Finding.NOT_ACTIVATED,
            config.host,
            f"{config.host} answered, but serves no CCAPI. It needs Canon's "
            "one-time activation, and CCAPI switched on in its menu.",
        )
    except UnacceptableVersionError as exc:
        return Verdict(Finding.INCOMPATIBLE, config.host, str(exc))
    except UnreachableError:
        return Verdict(
            Finding.UNREACHABLE,
            config.host,
            f"nothing answered at {config.base_url}. Check the camera is awake, "
            "on this network, and not already connected to something else.",
        )
    except CcapiError as exc:
        return Verdict(Finding.REFUSED, config.host, f"{config.host} refused: {exc}")
    finally:
        probing.disconnect()
    return Verdict(Finding.SERVING, config.host, f"{config.host} will serve")
