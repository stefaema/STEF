"""HTTP connection to a camera and the requests sent over it."""

from __future__ import annotations

import json as jsonlib
import logging
import threading
import time
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

from portable.ccapi.config import CameraConfig
from portable.ccapi.endpoints import API_ROOT, Methods, Registry
from portable.ccapi.errors import (
    CcapiError,
    NotActivatedError,
    NotConnectedError,
    UnacceptableVersionError,
    UnreachableError,
    error_for,
    worth_retrying,
)
from portable.ccapi.vocabulary import LinkState, error_body

GET = "GET"
POST = "POST"
PUT = "PUT"
DELETE = "DELETE"

log = logging.getLogger("ccapi.link")


@dataclass(frozen=True, slots=True)
class RawReply:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    chunks: Iterator[bytes] | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        loaded = jsonlib.loads(self.body)
        return loaded if isinstance(loaded, dict) else {"value": loaded}


class Transport(Protocol):
    def send(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
        stream: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> RawReply: ...

    def close(self) -> None: ...


class HttpTransport:
    def __init__(self, config: CameraConfig) -> None:
        import requests

        self._requests = requests
        self._control = requests.Session()
        self._bulk = requests.Session()
        if config.auth is not None:
            from requests.auth import HTTPDigestAuth

            credentials = HTTPDigestAuth(config.auth.username, config.auth.password)
            self._control.auth = credentials
            self._bulk.auth = credentials

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
        session = self._bulk if stream else self._control
        try:
            reply = session.request(
                method,
                url,
                json=payload,
                timeout=timeout,
                stream=stream,
                headers=dict(headers or {}),
            )
        except self._requests.RequestException as exc:
            raise UnreachableError(f"{type(exc).__name__}: {exc}") from exc
        return RawReply(
            status=reply.status_code,
            headers=dict(reply.headers),
            body=b"" if stream else reply.content,
            chunks=reply.iter_content(chunk_size=None) if stream else None,
        )

    def close(self) -> None:
        self._control.close()
        self._bulk.close()


class Link:
    def __init__(
        self, config: CameraConfig, transport: Transport | None = None
    ) -> None:
        self.config = config
        self.retries = config.retries
        self.backoff = config.backoff
        self.registry = Registry(config.accepted_version)
        self._transport = transport
        self._owns_transport = transport is None
        self._state = LinkState.DOWN
        self._failure: str | None = None
        self._manifest_body: dict[str, Any] = {}
        self._lock = threading.Lock()

    @contextmanager
    def retrying(
        self, *, retries: int | None = None, backoff: float | None = None
    ) -> Generator[None]:
        """Hold a different retry policy for the duration, then put the old one back.

        Only the two numbers `_request` counts with change. The transport, its
        sessions and their open connections are not built from them and never
        see this, so a routine may ask for a different policy mid-run without
        costing a reconnection.

        A caller that wants to see `DeviceBusyError` itself, and time its own
        wait, asks for `retries=0`.
        """
        was = (self.retries, self.backoff)
        if retries is not None:
            self.retries = retries
        if backoff is not None:
            self.backoff = backoff
        try:
            yield
        finally:
            self.retries, self.backoff = was

    @property
    def state(self) -> LinkState:
        return self._state

    @property
    def failure(self) -> str | None:
        return self._failure

    @property
    def up(self) -> bool:
        return self._state is LinkState.UP

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest_body)

    @property
    def version(self) -> str | None:
        found = self.registry.versions
        return found[-1] if found else None

    def connect(self) -> None:
        if self.up:
            return
        self._state = LinkState.CONNECTING
        self._failure = None
        log.debug("connecting to %s", self.config.base_url)
        try:
            manifest = self._manifest()
            self.registry.load(manifest)
            self._manifest_body = manifest
            if not self.registry.loaded:
                raise UnacceptableVersionError(
                    "the camera offers no API version this client accepts: "
                    f"{', '.join(self.registry.offered_beyond_accepted)}"
                )
        except CcapiError as exc:
            self.registry.clear()
            self._failure = str(exc)
            self._state = (
                LinkState.DOWN if isinstance(exc, UnreachableError) else LinkState.ERROR
            )
            log.error("could not connect to %s: %s", self.config.base_url, exc)
            raise
        self._state = LinkState.UP
        declined = self.registry.offered_beyond_accepted
        if declined:
            log.warning(
                "%s also offers %s, above the accepted %s",
                self.config.base_url,
                ", ".join(declined),
                self.config.accepted_version,
            )
        log.info(
            "connected to %s speaking %s, %d endpoints",
            self.config.base_url,
            ", ".join(self.registry.versions),
            len(self.registry.features),
        )

    def disconnect(self) -> None:
        if self.up:
            log.info("disconnecting from %s", self.config.base_url)
        self.registry.clear()
        self._manifest_body = {}
        self._state = LinkState.DOWN
        self._failure = None
        if self._owns_transport and self._transport is not None:
            self._transport.close()
            self._transport = None

    def _manifest(self) -> dict[str, Any]:
        reply = self._send(GET, f"{self.config.base_url}/{API_ROOT}")
        if reply.status == 404:
            raise NotActivatedError(
                f"something answered at {self.config.base_url}, but it serves "
                "no CCAPI root. The camera needs Canon's one-time activation, "
                "and CCAPI enabled in its menu.",
                404,
            )
        if not reply.ok:
            raise error_for(reply.status, error_body(reply.json()))
        return reply.json()

    def url_for(self, feature: str, *tail: str) -> str:
        path = self.registry.path_for(feature)
        whole = "/".join((path.rstrip("/"), *(part.strip("/") for part in tail)))
        if whole.startswith(("http://", "https://")):
            return whole
        return f"{self.config.base_url}/{whole.lstrip('/')}"

    def allows(self, feature: str, method: Methods) -> bool:
        return self.registry.offers(feature) and self.registry.methods_for(
            feature
        ).__contains__(method)

    def json(
        self,
        method: str,
        feature: str,
        *tail: str,
        payload: dict[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        reply = self._request(
            method, self.url_for(feature, *tail), payload=payload, query=query
        )
        return reply.json()

    def blob(
        self,
        feature: str,
        *tail: str,
        query: Mapping[str, str] | None = None,
        byte_range: tuple[int, int] | None = None,
    ) -> bytes:
        headers = (
            {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else None
        )
        reply = self._request(
            GET, self.url_for(feature, *tail), query=query, headers=headers
        )
        return reply.body

    def chunks(
        self,
        feature: str,
        *tail: str,
        query: Mapping[str, str] | None = None,
    ) -> Iterator[bytes]:
        reply = self._request(
            GET, self.url_for(feature, *tail), query=query, stream=True
        )
        return reply.chunks or iter(())

    def _request(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        query: Mapping[str, str] | None = None,
        stream: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> RawReply:
        if not self.up:
            raise NotConnectedError("the camera is not connected")
        whole = f"{url}?{urlencode(dict(query))}" if query else url
        for attempt in range(self.retries + 1):
            reply = self._send(
                method, whole, payload=payload, stream=stream, headers=headers
            )
            if reply.ok:
                return reply
            refusal = error_for(reply.status, error_body(reply.json()))
            if not worth_retrying(refusal):
                log.debug(
                    "%s %s refused, and waiting would not help: %s",
                    method,
                    whole,
                    refusal,
                )
                raise refusal
            if attempt == self.retries:
                log.warning(
                    "%s %s still refused after %d attempts: %s",
                    method,
                    whole,
                    attempt + 1,
                    refusal,
                )
                raise refusal
            pause = self.backoff * (2**attempt)
            log.debug(
                "%s %s refused (%s), waiting %.1fs", method, whole, refusal, pause
            )
            time.sleep(pause)
        raise NotConnectedError("the request loop ended without a reply")

    def _send(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        stream: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> RawReply:
        transport = self._ensure_transport()
        with self._lock:
            return transport.send(
                method,
                url,
                payload=payload,
                timeout=self.config.timeout,
                stream=stream,
                headers=headers,
            )

    def _ensure_transport(self) -> Transport:
        if self._transport is None:
            self._transport = HttpTransport(self.config)
            self._owns_transport = True
        return self._transport
