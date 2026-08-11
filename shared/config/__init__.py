import tomllib
from pathlib import Path
from typing import Any

from shared import paths

SUFFIX = ".toml"


class ConfigError(Exception):
    pass


def get(package: str, *parts: str) -> dict[str, Any]:
    found = paths.readable(package, *parts)
    if not found:
        shipped, mine = paths.layered(package, *parts)
        raise ConfigError(f"neither {shipped} nor {mine} is there")
    settled: dict[str, Any] = {}
    for file in found:
        settled = _overlaid(settled, _read(file))
    return settled


def available(package: str, *parts: str) -> tuple[str, ...]:
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


def _read(file: Path) -> dict[str, Any]:
    try:
        text = file.read_text()
    except OSError as exc:
        raise ConfigError(f"{file} cannot be read: {exc}") from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file} is not readable TOML: {exc}") from exc


def _overlaid(under: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    settled = dict(under)
    for key, value in over.items():
        beneath = settled.get(key)
        if isinstance(value, dict) and isinstance(beneath, dict):
            settled[key] = _overlaid(beneath, value)
        else:
            settled[key] = value
    return settled
