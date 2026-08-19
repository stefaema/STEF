"""The flashable images this machine has, and the one it is meant to run.

A flash is not a file. An ESP-IDF board needs a bootloader, a partition table
and an app, each written at its own offset, and only the build knows what those
offsets were. So the unit here is a directory holding those binaries and one
manifest saying where each goes, and the inventory is a directory of those.

A machine holds one release at a time, because installing replaces rather than
adds. Which of them a board ought to be running is not declared anywhere: it is
whichever one `fw_api` says this build can talk to.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from shared import fw_api, paths

MANIFEST = "manifest.json"
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
    backend: str
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
            backend=described["backend"],
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
    """Return the versions a form may offer, with the usable one standing for itself."""
    return (AUTO, *(release.version for release in installed()))


# ── The one this installation runs ───────────────────────────────────────────


def usable() -> tuple[Release, ...]:
    """Return the installed releases this build could talk to once one is flashed."""
    return tuple(r for r in installed() if fw_api.compatible(r.backend, r.version))


def resolve(version: str = AUTO) -> Release:
    """Return the release a form's choice names, `auto` meaning the one that fits."""
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

    fit = usable()
    if len(fit) == 1:
        return fit[0]
    if not fit:
        names = ", ".join(f"{r.backend} {r.version}" for r in have)
        raise ImageError(
            f"nothing installed speaks {fw_api.FW_API_BACKEND} "
            f"{fw_api.FW_API_VERSION}, so 'auto' names nothing; have: {names}"
        )
    names = ", ".join(r.version for r in fit)
    raise ImageError(
        f"several installed releases speak {fw_api.FW_API_VERSION}, so 'auto' names "
        f"nothing; installing replaces rather than adds, so remove the ones that do "
        f"not belong here or choose: {names}"
    )


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
