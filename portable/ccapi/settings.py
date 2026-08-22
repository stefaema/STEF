"""Shooting settings, read and written by name."""

from __future__ import annotations

import enum
from typing import Any

from portable.ccapi.link import GET, PUT, Link
from portable.ccapi.vocabulary import (
    ImageQuality,
    SettingValue,
    image_quality,
    setting_value,
)


class Setting(enum.StrEnum):
    AEB = "shooting/settings/aeb"
    AF = "shooting/settings/af"
    AFMETHOD = "shooting/settings/afmethod"
    AFOPERATION = "shooting/settings/afoperation"
    ANTIFLICKERSHOOT = "shooting/settings/antiflickershoot"
    APERTUREBRACKET = "shooting/settings/aperturebracket"
    AV = "shooting/settings/av"
    COLORSPACE = "shooting/settings/colorspace"
    COLORTEMPERATURE = "shooting/settings/colortemperature"
    DRIVE = "shooting/settings/drive"
    DRIVE_CUSTOMHIGHSPEEDCONT_NUMBEROFSHOTS = (
        "shooting/settings/drive/customhighspeedcont/numberofshots"
    )
    DRIVE_CUSTOMHIGHSPEEDCONT_SHOOTINGSPEED = (
        "shooting/settings/drive/customhighspeedcont/shootingspeed"
    )
    EXPOSURE = "shooting/settings/exposure"
    FLASH = "shooting/settings/flash"
    FOCUS = "shooting/settings/focus"
    FOCUSBRACKETING = "shooting/settings/focusbracketing"
    FOCUSBRACKETING_CROPDEPTHCOMP = "shooting/settings/focusbracketing/cropdepthcomp"
    FOCUSBRACKETING_DEPTHCOMPOSITE = "shooting/settings/focusbracketing/depthcomposite"
    FOCUSBRACKETING_EXPOSURESMOOTHING = (
        "shooting/settings/focusbracketing/exposuresmoothing"
    )
    FOCUSBRACKETING_FOCUSINCREMENT = "shooting/settings/focusbracketing/focusincrement"
    FOCUSBRACKETING_NUMBEROFSHOTS = "shooting/settings/focusbracketing/numberofshots"
    FOCUSPOSITION = "shooting/settings/focusposition"
    HDR = "shooting/settings/hdr"
    HFANTIFLICKERSHOOT = "shooting/settings/hfantiflickershoot"
    HFFLICKERTV = "shooting/settings/hfflickertv"
    HIGHFRAMERATE = "shooting/settings/highframerate"
    ISMODE = "shooting/settings/ismode"
    ISO = "shooting/settings/iso"
    LVZOOM = "shooting/settings/lvzoom"
    METERING = "shooting/settings/metering"
    MOVIECROPPING = "shooting/settings/moviecropping"
    MOVIEFORMAT = "shooting/settings/movieformat"
    MOVIEQUALITY = "shooting/settings/moviequality"
    MOVIEQUALITY_FRAMERATE = "shooting/settings/moviequality/framerate"
    PICTURESTYLE = "shooting/settings/picturestyle"
    PICTURESTYLE_AUTO = "shooting/settings/picturestyle/auto"
    PICTURESTYLE_FAITHFUL = "shooting/settings/picturestyle/faithful"
    PICTURESTYLE_FINEDETAIL = "shooting/settings/picturestyle/finedetail"
    PICTURESTYLE_LANDSCAPE = "shooting/settings/picturestyle/landscape"
    PICTURESTYLE_MONOCHROME = "shooting/settings/picturestyle/monochrome"
    PICTURESTYLE_NEUTRAL = "shooting/settings/picturestyle/neutral"
    PICTURESTYLE_PORTRAIT = "shooting/settings/picturestyle/portrait"
    PICTURESTYLE_STANDARD = "shooting/settings/picturestyle/standard"
    PICTURESTYLE_USERDEF1 = "shooting/settings/picturestyle/userdef1"
    PICTURESTYLE_USERDEF1_BASEPICTURESTYLE = (
        "shooting/settings/picturestyle/userdef1/basepicturestyle"
    )
    PICTURESTYLE_USERDEF2 = "shooting/settings/picturestyle/userdef2"
    PICTURESTYLE_USERDEF2_BASEPICTURESTYLE = (
        "shooting/settings/picturestyle/userdef2/basepicturestyle"
    )
    PICTURESTYLE_USERDEF3 = "shooting/settings/picturestyle/userdef3"
    PICTURESTYLE_USERDEF3_BASEPICTURESTYLE = (
        "shooting/settings/picturestyle/userdef3/basepicturestyle"
    )
    POWERZOOM = "shooting/settings/powerzoom"
    SHOOTINGMODE = "shooting/settings/shootingmode"
    MODE_DIAL_POSITION = "shooting/settings/shootingmodedial"
    SHOOTINGMODEDIAL_MOVIE = "shooting/settings/shootingmodedial/movie"
    SHUTTERMODE = "shooting/settings/shuttermode"
    SOUNDRECORDING = "shooting/settings/soundrecording"
    SOUNDRECORDING_ATTENUATOR = "shooting/settings/soundrecording/attenuator"
    SOUNDRECORDING_ATTENUATOR_ACC = "shooting/settings/soundrecording/attenuator/acc"
    SOUNDRECORDING_ATTENUATOR_ACC1 = "shooting/settings/soundrecording/attenuator/acc1"
    SOUNDRECORDING_ATTENUATOR_ACC2 = "shooting/settings/soundrecording/attenuator/acc2"
    SOUNDRECORDING_ATTENUATOR_EXTMIC = (
        "shooting/settings/soundrecording/attenuator/extmic"
    )
    SOUNDRECORDING_ATTENUATOR_INTMIC = (
        "shooting/settings/soundrecording/attenuator/intmic"
    )
    SOUNDRECORDING_LEVEL = "shooting/settings/soundrecording/level"
    SOUNDRECORDING_LEVEL_ACC = "shooting/settings/soundrecording/level/acc"
    SOUNDRECORDING_LEVEL_ACC1 = "shooting/settings/soundrecording/level/acc1"
    SOUNDRECORDING_LEVEL_ACC2 = "shooting/settings/soundrecording/level/acc2"
    SOUNDRECORDING_LEVEL_EXTMIC = "shooting/settings/soundrecording/level/extmic"
    SOUNDRECORDING_LEVEL_INTMIC = "shooting/settings/soundrecording/level/intmic"
    SOUNDRECORDING_MODE_ACC = "shooting/settings/soundrecording/mode/acc"
    SOUNDRECORDING_MODE_ACC1 = "shooting/settings/soundrecording/mode/acc1"
    SOUNDRECORDING_MODE_ACC2 = "shooting/settings/soundrecording/mode/acc2"
    SOUNDRECORDING_MODE_EXTMIC = "shooting/settings/soundrecording/mode/extmic"
    SOUNDRECORDING_MODE_INTMIC = "shooting/settings/soundrecording/mode/intmic"
    SOUNDRECORDING_WINDFILTER = "shooting/settings/soundrecording/windfilter"
    SOUNDRECORDING_WINDFILTER_ACC = "shooting/settings/soundrecording/windfilter/acc"
    SOUNDRECORDING_WINDFILTER_ACC1 = "shooting/settings/soundrecording/windfilter/acc1"
    SOUNDRECORDING_WINDFILTER_ACC2 = "shooting/settings/soundrecording/windfilter/acc2"
    SOUNDRECORDING_WINDFILTER_EXTMIC = (
        "shooting/settings/soundrecording/windfilter/extmic"
    )
    SOUNDRECORDING_WINDFILTER_INTMIC = (
        "shooting/settings/soundrecording/windfilter/intmic"
    )
    STILLIMAGEASPECTRATIO = "shooting/settings/stillimageaspectratio"
    STILLIMAGECOMPRESSION_LARGE = "shooting/settings/stillimagecompression/large"
    STILLIMAGECOMPRESSION_MEDIUM = "shooting/settings/stillimagecompression/medium"
    STILLIMAGECOMPRESSION_MEDIUM1 = "shooting/settings/stillimagecompression/medium1"
    STILLIMAGECOMPRESSION_MEDIUM2 = "shooting/settings/stillimagecompression/medium2"
    STILLIMAGECOMPRESSION_SMALL = "shooting/settings/stillimagecompression/small"
    STILLIMAGECOMPRESSION_SMALL1 = "shooting/settings/stillimagecompression/small1"
    STILLIMAGECOMPRESSION_SMALL2 = "shooting/settings/stillimagecompression/small2"
    STILLIMAGEQUALITY = "shooting/settings/stillimagequality"
    TRACKINGSETTING = "shooting/settings/trackingsetting"
    TV = "shooting/settings/tv"
    WB = "shooting/settings/wb"
    WBBRACKET = "shooting/settings/wbbracket"
    WBSHIFT = "shooting/settings/wbshift"
    WHITEBALANCE = "shooting/settings/whitebalance"


class Settings:
    def __init__(self, link: Link) -> None:
        self.link = link

    def offers(self, setting: Setting) -> bool:
        return self.link.registry.offers(setting)

    def get(self, setting: Setting) -> SettingValue:
        return setting_value(self.link.json(GET, setting))

    def set(self, setting: Setting, value: Any) -> None:
        self.link.json(PUT, setting, payload={"value": value})

    def allowed(self, setting: Setting) -> tuple[Any, ...]:
        return self.get(setting).allowed

    def image_quality(self) -> ImageQuality:
        """Return still image quality, which `get` cannot represent."""
        return image_quality(self.link.json(GET, Setting.STILLIMAGEQUALITY))

    def set_image_quality(self, raw: str, jpeg: str) -> None:
        """Set the raw and jpeg values of still image quality."""
        self.link.json(
            PUT,
            Setting.STILLIMAGEQUALITY,
            payload={"value": {"raw": raw, "jpeg": jpeg}},
        )

    def apply(self, recipe: dict[Setting, Any]) -> dict[Setting, Any]:
        for setting, value in recipe.items():
            self.set(setting, value)
        return {setting: self.get(setting).value for setting in recipe}

    def disagreeing(self, recipe: dict[Setting, Any]) -> dict[Setting, Any]:
        readback = {setting: self.get(setting).value for setting in recipe}
        return {
            setting: found
            for setting, found in readback.items()
            if found != recipe[setting]
        }
