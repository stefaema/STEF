"""A file's shipped default and this machine's copy of it, read as one."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared import paths
from shared.subsystem import SubsystemSpec

SUFFIX = ".toml"


class ConfigError(Exception):
    """Anything that leaves a setting unreadable."""


def get(package: str, *parts: str) -> dict[str, Any]:
    """Return one file's settings, yours laid over the shipped copy key by key.

    `parts` names the file below either root, one path segment per argument.
    """
    found = paths.readable(package, *parts)
    if not found:
        shipped, mine = paths.layered(package, *parts)
        raise ConfigError(f"neither {shipped} nor {mine} is there")
    settled: dict[str, Any] = {}
    for file in found:
        settled = _overlaid(settled, _read(file))
    return settled


def available(package: str, *parts: str) -> tuple[str, ...]:
    """Return the stem of every TOML file there is to choose from, each named once.

    `parts` names the directory to look in, where `get` names a file in it.
    """
    found: set[str] = set()
    for directory in (
        paths.builtin(package, *parts),
        paths.config_dir().joinpath(*parts),
    ):
        if not directory.is_dir():
            continue
        found.update(
            file.stem
            for file in directory.iterdir()
            if file.is_file() and file.suffix == SUFFIX
        )
    return tuple(sorted(found))


# ── What one subsystem was told ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SubsystemConfig:
    """Everything one subsystem was told, found under its own package."""

    package: str

    def get(self, *parts: str) -> dict[str, Any]:
        """Return one of this subsystem's files, its own laid over the shipped copy."""
        return get(self.package, *parts)

    def available(self, *parts: str) -> tuple[str, ...]:
        """Return the stem of every file this subsystem has to choose from."""
        return available(self.package, *parts)


def derive(spec: SubsystemSpec) -> SubsystemConfig:
    """Return the settings one subsystem reads, bound to the package they live under."""
    return SubsystemConfig(package=spec.package)


def _read(file: Path) -> dict[str, Any]:
    """Return the file parsed, naming it in either way it can fail."""
    try:
        text = file.read_text()
    except OSError as exc:
        raise ConfigError(f"{file} cannot be read: {exc}") from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file} is not readable TOML: {exc}") from exc


def _overlaid(under: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Return `under` with `over` on top, merging tables and replacing all else.

    A list in `over` therefore stands in for the shipped list rather than adding
    to it: there is no key to merge two entries by.
    """
    settled = dict(under)
    for key, value in over.items():
        beneath = settled.get(key)
        if isinstance(value, dict) and isinstance(beneath, dict):
            settled[key] = _overlaid(beneath, value)
        else:
            settled[key] = value
    return settled
