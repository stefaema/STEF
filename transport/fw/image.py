"""The flashable images this machine has, and the one it is meant to run.

A flash is not a file. An ESP-IDF board needs a bootloader, a partition table
and an app, each written at its own offset, and only the build knows what those
offsets were. So the unit here is a directory holding those binaries and one
manifest saying where each goes, and the inventory is a directory of those.

Which of them this installation runs is pinned rather than guessed. Taking the
newest would mean that dropping a file into a directory silently upgrades the
deployment, and a machine should say what it runs.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from shared import paths

MANIFEST = "manifest.json"
PIN_FILE = "firmware.toml"
AUTO = "auto"
READ_CHUNK = 1 << 20


class ImageError(Exception):
    """An image that cannot be trusted to reach a board intact."""


@dataclass(frozen=True, slots=True)
class Binary:
    """One file of a release, and the offset the build says it belongs at."""

    offset: int
    path: Path
    sha256: str

    @property
    def size(self) -> int:
        """Return how many bytes will go on the wire for this one."""
        return self.path.stat().st_size


@dataclass(frozen=True, slots=True)
class Release:
    """One version's worth of binaries, and what the build knew about them."""

    version: str
    project: str
    idf: str
    chip: str
    flash_size: str
    flash_mode: str
    flash_freq: str
    binaries: tuple[Binary, ...]
    directory: Path

    @property
    def total(self) -> int:
        """Return how many bytes a whole flash writes."""
        return sum(b.size for b in self.binaries)

    def fits(self, chip: str) -> bool:
        """Whether this release was built for the chip that answered."""
        return chip.lower().replace("-", "") == self.chip.lower().replace("-", "")


def _binary(directory: Path, entry: dict) -> Binary:
    """Return one manifest entry as a binary, refusing one that is not there."""
    path = directory / entry["file"]
    if not path.is_file():
        raise ImageError(f"{directory.name} names {entry['file']}, which is missing")
    return Binary(
        offset=int(str(entry["offset"]), 0), path=path, sha256=entry["sha256"]
    )


def read(directory: Path) -> Release:
    """Return the release a directory holds, refusing one whose manifest disagrees with it."""
    manifest = directory / MANIFEST
    if not manifest.is_file():
        raise ImageError(f"{directory} carries no {MANIFEST}")
    try:
        described = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        raise ImageError(f"{manifest} is not readable JSON: {exc}") from exc

    try:
        return Release(
            version=described["version"],
            project=described["project"],
            idf=described.get("idf", ""),
            chip=described["chip"],
            flash_size=described.get("flash_size", "keep"),
            flash_mode=described.get("flash_mode", "keep"),
            flash_freq=described.get("flash_freq", "keep"),
            binaries=tuple(_binary(directory, e) for e in described["images"]),
            directory=directory,
        )
    except KeyError as exc:
        raise ImageError(f"{manifest} names no {exc.args[0]}") from exc


def installed() -> tuple[Release, ...]:
    """Return every release on this machine, skipping directories that are not one.

    A directory with no manifest is something an operator left there, not an
    image, and refusing the whole inventory over it would be unhelpful.
    """
    root = paths.firmware_bins()
    if not root.is_dir():
        return ()
    found = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            found.append(read(directory))
        except ImageError:
            continue
    return tuple(found)


def versions() -> tuple[str, ...]:
    """Return the versions a form may offer, with the pinned one standing for itself."""
    return (AUTO, *(release.version for release in installed()))


# ── The one this installation runs ───────────────────────────────────────────


def pinned() -> str | None:
    """Return the version this machine declares it runs, or None where it declares none."""
    pin = paths.config_dir() / PIN_FILE
    if not pin.is_file():
        return None
    try:
        return tomllib.loads(pin.read_text()).get("version") or None
    except tomllib.TOMLDecodeError as exc:
        raise ImageError(f"{pin} is not readable TOML: {exc}") from exc


def expected() -> str | None:
    """Return the version a board ought to be running, without ever guessing at it.

    A pin says it outright. Failing that, one installed release is not a guess
    but the only answer available, and several is a question only the operator
    can settle.
    """
    declared = pinned()
    if declared is not None:
        return declared
    have = installed()
    return have[0].version if len(have) == 1 else None


def resolve(version: str = AUTO) -> Release:
    """Return the release a form's choice names, `auto` meaning the pinned one."""
    have = installed()
    if not have:
        raise ImageError(
            f"no firmware is installed in {paths.firmware_bins()}; import one first"
        )
    if version != AUTO:
        found = next((r for r in have if r.version == version), None)
        if found is None:
            names = ", ".join(r.version for r in have)
            raise ImageError(
                f"no installed firmware is version {version}; have: {names}"
            )
        return found

    wanted = expected()
    if wanted is None:
        names = ", ".join(r.version for r in have)
        raise ImageError(
            f"several versions are installed and none is pinned, so 'auto' names "
            f"nothing; pin one or choose: {names}"
        )
    return resolve(wanted)


# ── Whether what is on disk is what the build made ───────────────────────────


def digest(path: Path) -> str:
    """Return one file's SHA-256, read in pieces so a large image costs no memory."""
    digested = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            digested.update(chunk)
    return digested.hexdigest()


def altered(release: Release) -> tuple[str, ...]:
    """Return the names of the binaries that no longer hash to what the manifest says."""
    return tuple(
        b.path.name for b in release.binaries if digest(b.path) != b.sha256.lower()
    )
