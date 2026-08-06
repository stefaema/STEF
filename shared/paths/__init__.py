"""Where a module's shipped files are, and where this machine's own files go."""

import importlib.util
import os
from pathlib import Path

# ── Names ────────────────────────────────────────────────────────────────────

APP = "stef"
ENV_HOME = "STEF_HOME"
BUILTIN = "builtin"

CONFIG = "config"
STATE = "state"
FIRMWARE = "firmware"

XDG_CONFIG = ("XDG_CONFIG_HOME", ".config")
XDG_STATE = ("XDG_STATE_HOME", ".local/state")
XDG_DATA = ("XDG_DATA_HOME", ".local/share")


# ── How this fails ───────────────────────────────────────────────────────────


class PathsError(Exception):
    """Anything that leaves a path undecidable."""


# ── The roots this machine writes under ──────────────────────────────────────


def _absolute(value: str | None) -> Path | None:
    """Return the value only if it is a path the spec would honour."""
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def home() -> Path | None:
    """Return the root STEF_HOME names, or None when it names nothing."""
    return _absolute(os.environ.get(ENV_HOME))


def _xdg(variable: str, fallback: str) -> Path:
    """Return the directory the variable names, or the spec's fallback."""
    return _absolute(os.environ.get(variable)) or Path.home() / fallback


def _root(under_home: str, xdg: tuple[str, str]) -> Path:
    """Return one runtime root, under STEF_HOME when developing."""
    developing = home()
    if developing is not None:
        return developing / under_home
    return _xdg(*xdg) / APP


def config_dir() -> Path:
    """Return where a machine's own settings live."""
    return _root(CONFIG, XDG_CONFIG)


def state_dir() -> Path:
    """Return where the program writes what it must remember."""
    return _root(STATE, XDG_STATE)


def data_dir() -> Path:
    """Return where the program keeps what it was given."""
    developing = home()
    if developing is not None:
        return developing
    return _xdg(*XDG_DATA) / APP


def firmware_dir() -> Path:
    """Return where the flashable images are kept, one directory per version."""
    return data_dir() / FIRMWARE


# ── What a package ships ─────────────────────────────────────────────────────


def package_dir(package: str) -> Path:
    """Return the directory a package's code sits in, installed or in a checkout."""
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError) as exc:
        raise PathsError(f"{package!r} is not importable from here") from exc
    if spec is None or spec.origin is None:
        raise PathsError(f"{package!r} has no directory on disk")
    return Path(spec.origin).parent


def builtin_dir(package: str) -> Path:
    """Return what the package ships, which no one is meant to edit in place."""
    return package_dir(package) / BUILTIN


def builtin(package: str, *parts: str) -> Path:
    """Return one shipped file by the name it has inside the package."""
    return builtin_dir(package).joinpath(*parts)


# ── The two places one file can live ─────────────────────────────────────────


def layered(package: str, *parts: str) -> tuple[Path, Path]:
    """Return the same file under both roots, shipped first and yours second."""
    if not parts:
        raise PathsError("name the file, not the directory it sits in")
    return builtin(package, *parts), config_dir().joinpath(*parts)


def readable(package: str, *parts: str) -> list[Path]:
    """Return the layered paths that exist, in the order they should be read."""
    return [path for path in layered(package, *parts) if path.is_file()]


# ── Making room to write ─────────────────────────────────────────────────────


def ensure(path: Path) -> Path:
    """Return the directory, creating it and its parents if they are missing."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    """Return the path with its directory made, leaving the file to the caller."""
    ensure(path.parent)
    return path
