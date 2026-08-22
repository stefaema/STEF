"""Parsed reply types and the functions that build them."""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from typing import Any


class LinkState(enum.Enum):
    DOWN = "down"
    CONNECTING = "connecting"
    UP = "up"
    ERROR = "error"


class ThermalRestriction(enum.Enum):
    NORMAL = "normal"
    WARNING = "warning"
    FRAME_RATE_DOWN = "frameratedown"
    LIVE_VIEW_REFUSED = "disableliveview"
    STILLS_REFUSED = "disablerelease"
    STILL_QUALITY_WARNING = "stillqualitywarning"
    MOVIE_RESTRICTED = "restrictionmovierecording"
    WARNING_MOVIE_RESTRICTED = "warning_and_restrictionmovierecording"
    FRAME_RATE_DOWN_MOVIE_RESTRICTED = "frameratedown_and_restrictionmovierecording"
    LIVE_VIEW_REFUSED_MOVIE_RESTRICTED = "disableliveview_and_restrictionmovierecording"
    STILLS_REFUSED_MOVIE_RESTRICTED = "disablerelease_and_restrictionmovierecording"
    STILL_QUALITY_WARNING_MOVIE_RESTRICTED = (
        "stillqualitywarning_and_restrictionmovierecording"
    )

    @property
    def stills_degraded(self) -> bool:
        return self in _STILLS_DEGRADED

    @property
    def stills_refused(self) -> bool:
        return self in _STILLS_REFUSED

    @property
    def live_view_refused(self) -> bool:
        return self in _LIVE_VIEW_REFUSED

    @property
    def worth_pausing(self) -> bool:
        return self is not ThermalRestriction.NORMAL


_STILLS_DEGRADED = frozenset(
    {
        ThermalRestriction.STILL_QUALITY_WARNING,
        ThermalRestriction.STILL_QUALITY_WARNING_MOVIE_RESTRICTED,
    }
)
_STILLS_REFUSED = frozenset(
    {
        ThermalRestriction.STILLS_REFUSED,
        ThermalRestriction.STILLS_REFUSED_MOVIE_RESTRICTED,
    }
)
_LIVE_VIEW_REFUSED = frozenset(
    {
        ThermalRestriction.LIVE_VIEW_REFUSED,
        ThermalRestriction.LIVE_VIEW_REFUSED_MOVIE_RESTRICTED,
    }
)


class PowerSource(enum.Enum):
    BATTERY = "battery"
    NOT_INSERTED = "not_inserted"
    AC_ADAPTER = "ac_adapter"
    DC_COUPLER = "dc_coupler"
    BATTERY_GRIP = "batterygrip"
    UNKNOWN = "unknown"

    @property
    def on_mains(self) -> bool:
        return self in (PowerSource.AC_ADAPTER, PowerSource.DC_COUPLER)


class PowerState(enum.Enum):
    LOW = "low"
    QUARTER = "quarter"
    HALF = "half"
    HIGH = "high"
    FULL = "full"
    UNKNOWN = "unknown"
    CHARGING = "charge"
    CHARGE_STOPPED = "chargestop"
    CHARGE_COMPLETE = "chargecomp"

    @property
    def is_charge_level(self) -> bool:
        return self in _CHARGE_LEVELS

    @property
    def charging(self) -> bool:
        return self in _CHARGING


_CHARGE_LEVELS = frozenset(
    {
        PowerState.LOW,
        PowerState.QUARTER,
        PowerState.HALF,
        PowerState.HIGH,
        PowerState.FULL,
    }
)
_CHARGING = frozenset(
    {
        PowerState.CHARGING,
        PowerState.CHARGE_STOPPED,
        PowerState.CHARGE_COMPLETE,
    }
)


class Access(enum.Enum):
    READ_WRITE = "readwrite"
    READ_ONLY = "readonly"

    @property
    def writable(self) -> bool:
        return self is Access.READ_WRITE


class ContentKind(enum.Enum):
    MAIN = "main"
    THUMBNAIL = "thumbnail"
    DISPLAY = "display"
    EMBEDDED = "embedded"


class FileType(enum.Enum):
    ALL = "all"
    JPEG = "jpeg"
    CR2 = "cr2"
    CR3 = "cr3"
    HEIF = "heif"
    MP4 = "mp4"
    MOV = "mov"
    WAV = "wav"


class PollWait(enum.Enum):
    IMMEDIATELY = "immediately"
    SHORT = "short"
    LONG = "long"


class PacketKind(enum.Enum):
    IMAGE = 0x00
    INCIDENTAL = 0x01
    EVENT = 0x02


@dataclass(frozen=True, slots=True)
class Packet:
    kind: PacketKind
    body: bytes


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    manufacturer: str
    product_name: str
    guid: str
    serial_number: str
    mac_address: str
    firmware_version: str


@dataclass(frozen=True, slots=True)
class BatteryInfo:
    name: str
    source: PowerSource
    power: PowerState

    @property
    def present(self) -> bool:
        return self.source is not PowerSource.NOT_INSERTED


@dataclass(frozen=True, slots=True)
class LensInfo:
    mounted: bool
    name: str


@dataclass(frozen=True, slots=True)
class Storage:
    name: str
    url: str
    access: Access
    capacity: int
    free: int
    file_count: int

    @property
    def free_fraction(self) -> float:
        return self.free / self.capacity if self.capacity else 0.0

    def holds(self, frames: int, bytes_each: int) -> bool:
        return self.free >= frames * bytes_each


@dataclass(frozen=True, slots=True)
class FileInfo:
    path: str
    size: int
    protected: bool


NO_FILE = "none"


@dataclass(frozen=True, slots=True)
class ImageQuality:
    """Still image quality, set as a raw value and a jpeg value."""

    raw: str
    jpeg: str
    raw_allowed: tuple[str, ...] = ()
    jpeg_allowed: tuple[str, ...] = ()

    @property
    def writes_raw(self) -> bool:
        return bool(self.raw) and self.raw != NO_FILE

    @property
    def writes_jpeg(self) -> bool:
        return bool(self.jpeg) and self.jpeg != NO_FILE

    @property
    def writes_two(self) -> bool:
        return self.writes_raw and self.writes_jpeg

    @property
    def offers_two(self) -> bool:
        return any(one != NO_FILE for one in self.raw_allowed) and any(
            one != NO_FILE for one in self.jpeg_allowed
        )


@dataclass(frozen=True, slots=True)
class SettingValue:
    value: Any
    allowed: tuple[Any, ...]

    @property
    def writable(self) -> bool:
        return bool(self.allowed)

    def accepts(self, candidate: Any) -> bool:
        return candidate in self.allowed


@dataclass(frozen=True, slots=True)
class ErrorBody:
    message: str


@dataclass(frozen=True, slots=True)
class StateChange:
    battery: BatteryInfo | None = None
    lens: LensInfo | None = None
    thermal: ThermalRestriction | None = None
    storage: tuple[Storage, ...] | None = None
    settings: dict[str, SettingValue] | None = None
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.battery,
                self.lens,
                self.thermal,
                self.storage,
                self.settings,
                self.added,
                self.removed,
                self.updated,
            )
        )


@dataclass(frozen=True, slots=True)
class CameraState:
    battery: BatteryInfo | None = None
    lens: LensInfo | None = None
    thermal: ThermalRestriction | None = None
    storage: tuple[Storage, ...] | None = None
    settings: dict[str, SettingValue] | None = None

    def merged(self, change: StateChange) -> CameraState:
        settings = self.settings
        if change.settings is not None:
            settings = {**(settings or {}), **change.settings}
        return replace(
            self,
            battery=change.battery if change.battery is not None else self.battery,
            lens=change.lens if change.lens is not None else self.lens,
            thermal=change.thermal if change.thermal is not None else self.thermal,
            storage=change.storage if change.storage is not None else self.storage,
            settings=settings,
        )


def device_info(body: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        manufacturer=body.get("manufacturer") or body.get("munufacturer", ""),
        product_name=body.get("productname", ""),
        guid=body.get("guid", ""),
        serial_number=body.get("serialnumber", ""),
        mac_address=body.get("macaddress", ""),
        firmware_version=body.get("firmwareversion", ""),
    )


def battery_info(body: dict[str, Any]) -> BatteryInfo:
    return BatteryInfo(
        name=body.get("name", ""),
        source=_member(PowerSource, body.get("kind"), PowerSource.UNKNOWN),
        power=_member(PowerState, body.get("level"), PowerState.UNKNOWN),
    )


def battery_list(body: dict[str, Any]) -> tuple[BatteryInfo, ...]:
    return tuple(battery_info(entry) for entry in body.get("batterylist", ()))


def lens_info(body: dict[str, Any]) -> LensInfo:
    return LensInfo(mounted=bool(body.get("mount")), name=body.get("name", ""))


def thermal(body: dict[str, Any]) -> ThermalRestriction:
    return _member(ThermalRestriction, body.get("status"), ThermalRestriction.NORMAL)


def storage_list(body: dict[str, Any]) -> tuple[Storage, ...]:
    return tuple(storage(entry) for entry in body.get("storagelist", ()))


def storage(entry: dict[str, Any]) -> Storage:
    return Storage(
        name=entry.get("name", ""),
        url=entry.get("url", ""),
        access=_member(Access, entry.get("accesscapability"), Access.READ_ONLY),
        capacity=int(entry.get("maxsize") or entry.get("maxize") or 0),
        free=int(entry.get("spacesize") or 0),
        file_count=int(entry.get("contentsnumber") or 0),
    )


def setting_value(body: dict[str, Any]) -> SettingValue:
    """Return a setting's value, and its allowed values when `ability` is a list."""
    ability = body.get("ability")
    return SettingValue(
        value=body.get("value"),
        allowed=tuple(ability) if isinstance(ability, (list, tuple)) else (),
    )


def image_quality(body: dict[str, Any]) -> ImageQuality:
    """Return still image quality, whose value and ability are objects."""
    value = body.get("value")
    ability = body.get("ability")
    value = value if isinstance(value, dict) else {}
    ability = ability if isinstance(ability, dict) else {}
    return ImageQuality(
        raw=str(value.get("raw", "")),
        jpeg=str(value.get("jpeg", "")),
        raw_allowed=tuple(str(one) for one in ability.get("raw") or ()),
        jpeg_allowed=tuple(str(one) for one in ability.get("jpeg") or ()),
    )


def file_info(path: str, body: dict[str, Any]) -> FileInfo:
    return FileInfo(
        path=path,
        size=int(body.get("filesize") or 0),
        protected=str(body.get("protect", "")).lower() in ("on", "true"),
    )


def error_body(body: dict[str, Any]) -> ErrorBody:
    return ErrorBody(message=str(body.get("message", "")))


def state_change(body: dict[str, Any]) -> StateChange:
    known = {"battery", "lens", "temperature", "storage"}
    settings = {
        key: setting_value(value)
        for key, value in body.items()
        if key not in known and isinstance(value, dict) and "value" in value
    }
    return StateChange(
        battery=battery_info(body["battery"]) if "battery" in body else None,
        lens=lens_info(body["lens"]) if "lens" in body else None,
        thermal=thermal(body["temperature"]) if "temperature" in body else None,
        storage=storage_list(body) if "storage" in body else None,
        settings=settings or None,
        added=tuple(body.get("addedcontents") or ()),
        removed=tuple(body.get("deletedcontents") or ()),
        updated=tuple(body.get("updatedcontents") or ()),
    )


def _member(kind: Any, raw: Any, fallback: Any) -> Any:
    try:
        return kind(raw)
    except ValueError:
        return fallback
