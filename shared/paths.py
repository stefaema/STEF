import importlib.util
import os
from pathlib import Path

APP = "stef"
ENV_HOME = "STEF_HOME"
BUILTIN = "builtin"

CONFIG = "config"
STATE = "state"
FIRMWARE = "firmware"

XDG_CONFIG = ("XDG_CONFIG_HOME", ".config")
XDG_STATE = ("XDG_STATE_HOME", ".local/state")
XDG_DATA = ("XDG_DATA_HOME", ".local/share")


class PathsError(Exception):
    pass


def _absolute(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def home() -> Path | None:
    return _absolute(os.environ.get(ENV_HOME))


def _xdg(variable: str, fallback: str) -> Path:
    return _absolute(os.environ.get(variable)) or Path.home() / fallback


def _root(under_home: str, xdg: tuple[str, str]) -> Path:
    developing = home()
    if developing is not None:
        return developing / under_home
    return _xdg(*xdg) / APP


def config_dir() -> Path:
    return _root(CONFIG, XDG_CONFIG)


def state_dir() -> Path:
    return _root(STATE, XDG_STATE)


def data_dir() -> Path:
    developing = home()
    if developing is not None:
        return developing
    return _xdg(*XDG_DATA) / APP


def firmware_dir() -> Path:
    return data_dir() / FIRMWARE


def package_dir(package: str) -> Path:
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError) as exc:
        raise PathsError(f"{package!r} is not importable from here") from exc
    if spec is None or spec.origin is None:
        raise PathsError(f"{package!r} has no directory on disk")
    return Path(spec.origin).parent


def builtin_dir(package: str) -> Path:
    return package_dir(package) / BUILTIN


def builtin(package: str, *parts: str) -> Path:
    return builtin_dir(package).joinpath(*parts)


def layered(package: str, *parts: str) -> tuple[Path, Path]:
    if not parts:
        raise PathsError("name the file, not the directory it sits in")
    return builtin(package, *parts), config_dir().joinpath(*parts)


def readable(package: str, *parts: str) -> list[Path]:
    return [path for path in layered(package, *parts) if path.is_file()]


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    ensure(path.parent)
    return path
