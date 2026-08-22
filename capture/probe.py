"""Which cameras are on the network, and whether they will answer, without disturbing them."""

from __future__ import annotations

import enum
import selectors
import socket
import struct
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from urllib.parse import urlparse

from portable.ccapi import (
    DEFAULT_PORT,
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
WAIT = 2.0
HOP = 2
LOOPBACK = "lo"
ANY = b"\x00\x00\x00\x00"
DEFAULT_ROUTE = 0

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
    held: bool
    ssl: bool = False

    @property
    def address(self) -> str:
        """Return where CCAPI is served, naming a port only where it is unusual."""
        return self.host if self.port == DEFAULT_PORT else f"{self.host}:{self.port}"

    @property
    def label(self) -> str:
        """Return what to call it in a list, which is what it is plus what it admits."""
        said = self.model or "camera"
        if self.serial:
            said = f"{said} {self.serial[-6:]}"
        if self.held:
            said = f"{said}, in use"
        return f"{self.address} ({said})"


@dataclass(frozen=True, slots=True)
class Sweep:
    """One discovery search, and enough of how it went to tell silence apart.

    An empty result has three causes that look identical from a camera list:
    no interface carried the search, the search went out and nothing came back,
    or something answered and then would not describe itself. Each wants a
    different thing from the operator, so each is recorded separately.
    """

    found: tuple[Found, ...]
    carried: tuple[str, ...]
    refused: tuple[str, ...]
    answered: int

    def __bool__(self) -> bool:
        """Return whether a camera was found, so a sweep reads like its result."""
        return bool(self.found)

    @property
    def sentence(self) -> str:
        """Return what this sweep settled, in the words an operator reads."""
        if self.found:
            return f"{len(self.found)} camera(s) answered"
        if not self.carried:
            return (
                "no interface carried a discovery search, so nothing was asked. "
                "Check this host is on the camera's network."
            )
        where = ", ".join(self.carried)
        if self.answered:
            return (
                f"{self.answered} device(s) answered on {where}, and none of them "
                "would describe itself"
            )
        return (
            f"nothing answered on {where}. A camera reached by address alone is "
            "still there: discovery is multicast, and an access point or switch "
            "between it and here may be dropping it."
        )


# ── Asking the network ───────────────────────────────────────────────────────


def search(wait: float = WAIT) -> tuple[Found, ...]:
    """Return every camera that answers a discovery search, in address order."""
    return sweep(wait).found


def sweep(wait: float = WAIT) -> Sweep:
    """Return what a discovery search turned up, and how far it got when nothing did.

    Multicast, so this reaches one subnet and no further, and an access point
    or switch that drops it makes a present camera invisible. Silence is not
    an answer, which is why the result records what was asked and of whom.
    """
    locations, carried, refused = _locations(wait)
    found: dict[str, Found] = {}
    for location in locations:
        described = describe(location)
        if described is not None:
            found[described.host] = described
    settled = Sweep(
        found=tuple(sorted(found.values(), key=lambda one: one.host)),
        carried=carried,
        refused=refused,
        answered=len(locations),
    )
    log.log("INFO" if settled else "WARNING", "{}", settled.sentence)
    for one in settled.found:
        log.info("found {}", one.label)
    return settled


def _locations(wait: float) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return every description URL answered, and which interfaces did the asking."""
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {GROUP}:{PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {max(1, round(wait))}\r\n"
        f"ST: {SERVICE}\r\n\r\n"
    ).encode()
    asked, refused = _asked_on(request)
    if not asked:
        return (), (), refused
    log.debug("discovery search went out of {}", ", ".join(asked.values()))
    try:
        return tuple(_replies(asked, wait)), tuple(asked.values()), refused
    finally:
        for sock in asked:
            sock.close()


def _asked_on(
    request: bytes,
) -> tuple[dict[socket.socket, str], tuple[str, ...]]:
    """Send one search out of every interface, and return the sockets that took it.

    Every interface and not the default route alone: a bench host with a wired
    network, a wireless one and a handful of container bridges has no single
    right answer, and the kernel's choice is the camera's only by luck.
    """
    took: dict[socket.socket, str] = {}
    refused: list[str] = []
    for name, index in _interfaces():
        sock = _sender(name, index)
        try:
            sock.sendto(request, (GROUP, PORT))
        except OSError as exc:
            log.debug("{} did not carry a discovery search: {}", name, exc)
            sock.close()
            refused.append(name)
            continue
        took[sock] = name
    return took, tuple(refused)


def _interfaces() -> tuple[tuple[str, int], ...]:
    """Return every interface worth asking out of, or the default route alone."""
    try:
        every = socket.if_nameindex()
    except (OSError, AttributeError) as exc:
        log.debug("interfaces could not be listed, using the default route: {}", exc)
        return (("default route", DEFAULT_ROUTE),)
    named = tuple((name, index) for index, name in every if name != LOOPBACK)
    return named or (("default route", DEFAULT_ROUTE),)


def _sender(name: str, index: int) -> socket.socket:
    """Return a socket that sends out of one named interface, whatever the route says."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, HOP)
    sock.setblocking(False)
    if index != DEFAULT_ROUTE:
        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                struct.pack("@4s4si", ANY, ANY, index),
            )
        except OSError as exc:
            log.debug("{} could not be chosen to send out of: {}", name, exc)
    return sock


def _replies(asked: dict[socket.socket, str], wait: float) -> list[str]:
    """Return each description URL answered once, listening on every socket at once."""
    seen: list[str] = []
    deadline = time.monotonic() + wait
    with selectors.DefaultSelector() as picker:
        for sock, name in asked.items():
            picker.register(sock, selectors.EVENT_READ, name)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            for key, _ in picker.select(left):
                _collect(key.fileobj, str(key.data), seen)  # type: ignore[arg-type]
    return seen


def _collect(sock: socket.socket, name: str, seen: list[str]) -> None:
    """Read one waiting reply and keep the description URL it names, once."""
    try:
        payload, sender = sock.recvfrom(4096)
    except OSError:
        return
    location = _header(payload.decode("utf-8", "replace"), "location")
    if not location:
        log.debug("{} answered on {} without a location", sender[0], name)
        return
    if location in seen:
        return
    log.debug("{} answered on {} with {}", sender[0], name, location)
    seen.append(location)


def _header(response: str, name: str) -> str:
    """Return one header out of an SSDP reply, matched however it was capitalised."""
    for line in response.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == name:
            return value.strip()
    return ""


# ── What one camera says about itself ────────────────────────────────────────


def describe(location: str) -> Found | None:
    """Return what one camera's description says, or None when it will not answer."""
    try:
        with urllib.request.urlopen(location, timeout=WAIT) as reply:
            document = reply.read()
    except (urllib.error.URLError, OSError) as exc:
        log.debug("{} did not describe itself: {}", location, exc)
        return None
    return _read(document, location)


def _read(document: bytes, location: str) -> Found | None:
    """Return a device description as the fields a list needs.

    The address CCAPI is served on is the one the description names, not the
    one it was fetched from: those are two servers on two ports, and only the
    first of them speaks CCAPI.
    """
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:
        log.debug("{} described itself unreadably: {}", location, exc)
        return None
    device = _element(root, "device")
    if device is None:
        log.debug("{} described no device", location)
        return None
    access = _text(device, "X_accessURL")
    if not access:
        log.debug("{} named no access URL, falling back to its own address", location)
    served = urlparse(access) if access else None
    host = (served.hostname if served else None) or urlparse(location).hostname
    if not host:
        log.debug("{} named no address to reach it on", location)
        return None
    return Found(
        host=host,
        port=(served.port if served else None) or DEFAULT_PORT,
        ssl=bool(served) and served.scheme == "https",  # type: ignore[union-attr]
        model=_text(device, "modelName") or _text(device, "friendlyName"),
        serial=_text(device, "serialNumber"),
        held=_text(device, "X_onService") == "1",
    )


def _element(root: ElementTree.Element, tag: str) -> ElementTree.Element | None:
    """Return the first element with this name, wherever it sits and whoever namespaced it.

    Canon's description mixes two namespaces and nests the fields that matter
    two levels below the device, so neither a plain name nor a fixed namespace
    finds all of them.
    """
    for node in root.iter():
        if _plain(node.tag) == tag:
            return node
    return None


def _text(root: ElementTree.Element, tag: str) -> str:
    """Return one tag's text, found by name alone."""
    node = _element(root, tag)
    return node.text.strip() if node is not None and node.text else ""


def _plain(tag: str) -> str:
    """Return a tag's name with whatever namespace prefixed it removed."""
    return tag.rpartition("}")[2]


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
    settled = _identified(config)
    log.log("INFO" if settled else "WARNING", "{}", settled.sentence)
    return settled


def _identified(config: CameraConfig) -> Verdict:
    """Connect far enough to place this address, and let go however that went."""
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
