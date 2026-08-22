"""Camera address and connection settings."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PORT = 8080
DEFAULT_SSL_PORT = 443


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class CameraConfig:
    host: str
    port: int = DEFAULT_PORT
    ssl: bool = False
    auth: Credentials | None = None
    timeout: float = 5.0
    retries: int = 3
    accepted_version: str | None = None

    @property
    def scheme(self) -> str:
        return "https" if self.ssl else "http"

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"
