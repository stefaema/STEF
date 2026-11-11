"""The firmware releases installed on this machine, and which one to flash.

A release is a directory holding the bootloader, the partition table and the
app, with a manifest giving each file's flash offset. Installing replaces the
previous release, so `auto` expects one release compatible with `fw_api`.
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
    """A release whose manifest or files cannot be used."""


@dataclass(frozen=True, slots=True)
class Binary:
    """One file of a release and its flash offset."""

    offset: int
    path: Path
    sha256: str

    @property
    def size(self) -> int:
        """Return the file size in bytes."""
        return self.path.stat().st_size


@dataclass(frozen=True, slots=True)
class Release:
    """One release: its binaries and the build settings from its manifest."""

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
        """Return the bytes a full flash writes."""
        return sum(b.size for b in self.binaries)

    def fits(self, chip: str) -> bool:
        """Return whether this release was built for `chip`."""
        return chip.lower().replace("-", "") == self.chip.lower().replace("-", "")


def _binary(directory: Path, entry: dict) -> Binary:
    """Return one manifest entry as a Binary, refusing one whose file is missing."""
    path = directory / entry["file"]
    if not path.is_file():
        raise ImageError(f"{directory.name} names {entry['file']}, which is missing")
    return Binary(
        offset=int(str(entry["offset"]), 0), path=path, sha256=entry["sha256"]
    )


def read(directory: Path) -> Release:
    """Return the release in `directory`, refusing a missing or incomplete manifest."""
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
    """Return every release on this machine, skipping directories without a usable manifest."""
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
    """Return the choices a form offers: `auto` and every installed version."""
    return (AUTO, *(release.version for release in installed()))


# ── Choosing the release ─────────────────────────────────────────────────────


def usable() -> tuple[Release, ...]:
    """Return the installed releases compatible with this build's `fw_api`."""
    return tuple(r for r in installed() if fw_api.compatible(r.backend, r.version))


def resolve(version: str = AUTO) -> Release:
    """Return the release named by `version`, where `auto` picks the one compatible release."""
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
        f"nothing; remove the extra ones or choose: {names}"
    )


# ── Checking the files against the manifest ──────────────────────────────────


def digest(path: Path) -> str:
    """Return a file's SHA-256, read in chunks."""
    digested = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            digested.update(chunk)
    return digested.hexdigest()


def altered(release: Release) -> tuple[str, ...]:
    """Return the names of the binaries whose hash differs from the manifest."""
    return tuple(
        b.path.name for b in release.binaries if digest(b.path) != b.sha256.lower()
    )
