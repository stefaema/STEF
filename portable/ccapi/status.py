from __future__ import annotations

from portable.ccapi.endpoints import Endpoint
from portable.ccapi.link import GET, Link
from portable.ccapi.vocabulary import (
    BatteryInfo,
    DeviceInfo,
    LensInfo,
    ThermalRestriction,
    battery_info,
    battery_list,
    device_info,
    lens_info,
    thermal,
)


class Status:
    def __init__(self, link: Link) -> None:
        self.link = link

    def device(self) -> DeviceInfo:
        return device_info(self.link.json(GET, Endpoint.DEVICEINFORMATION))

    def battery(self) -> BatteryInfo:
        return battery_info(self.link.json(GET, Endpoint.BATTERY))

    def batteries(self) -> tuple[BatteryInfo, ...]:
        return battery_list(self.link.json(GET, Endpoint.BATTERYLIST))

    def lens(self) -> LensInfo:
        return lens_info(self.link.json(GET, Endpoint.LENS))

    def thermal(self) -> ThermalRestriction:
        return thermal(self.link.json(GET, Endpoint.TEMPERATURE))

    def release_count(self) -> int:
        body = self.link.json(GET, Endpoint.RELEASECOUNT)
        return int(body.get("releasecount") or 0)

    def recordable(self) -> str:
        body = self.link.json(GET, Endpoint.RECORDABLE)
        return str(body.get("status", ""))
