from __future__ import annotations

import enum
from dataclasses import dataclass

API_ROOT = "ccapi"


class Methods(enum.Flag):
    GET = enum.auto()
    POST = enum.auto()
    PUT = enum.auto()
    DELETE = enum.auto()


class Volatility(enum.Enum):
    VOLATILE = "volatile"
    OWNED = "owned"
    CONSTANT = "constant"


class Endpoint(enum.StrEnum):
    CONTENTS = "contents"
    CF_EXPOSUREINCREMENTS_AV = "customfunction/exposureincrements/av"
    CF_EXPOSUREINCREMENTS_EXPOSURE = "customfunction/exposureincrements/exposure"
    CF_EXPOSUREINCREMENTS_FLASHEXPOSURE = (
        "customfunction/exposureincrements/flashexposure"
    )
    CF_EXPOSUREINCREMENTS_TV = "customfunction/exposureincrements/tv"
    CF_ISOINCREMENTS = "customfunction/isoincrements"
    DEVICEINFORMATION = "deviceinformation"
    BATTERY = "devicestatus/battery"
    BATTERYLIST = "devicestatus/batterylist"
    CURRENTDIRECTORY = "devicestatus/currentdirectory"
    CURRENTSTORAGE = "devicestatus/currentstorage"
    LENS = "devicestatus/lens"
    POWERZOOMSTATUS = "devicestatus/powerzoomstatus"
    RELEASECOUNT = "devicestatus/releasecount"
    STORAGE = "devicestatus/storage"
    TEMPERATURE = "devicestatus/temperature"
    MONITORING = "event/monitoring"
    POLLING = "event/polling"
    AUTOPOWEROFF = "functions/autopoweroff"
    BEEP = "functions/beep"
    CARDFORMAT = "functions/cardformat"
    CARDSELECTION_MOVIE = "functions/cardselection/movie"
    CARDSELECTION_STILLIMAGE = "functions/cardselection/stillimage"
    CONNECTSETTING = "functions/connectsetting"
    CORS_CORSSETTING = "functions/cors/corssetting"
    CORS_ORIGIN = "functions/cors/origin"
    DATETIME = "functions/datetime"
    DIRECTORY_CREATEDIRECTORY = "functions/directory/createdirectory"
    DIRECTORY_DIRECTORYSELECTION = "functions/directory/directoryselection"
    DISPLAYOFF = "functions/displayoff"
    FANMODE = "functions/fanmode"
    FANSPEED = "functions/fanspeed"
    FILENAME_MOVIES_INDEX = "functions/filename/movies/index"
    FILENAME_MOVIES_REELNUM = "functions/filename/movies/reelnum"
    FILENAME_MOVIES_USERDEFINED = "functions/filename/movies/userdefined"
    FILENAME_STILLS_FILENAME = "functions/filename/stills/filename"
    FILENAME_STILLS_USERSETTING1 = "functions/filename/stills/usersetting1"
    FILENAME_STILLS_USERSETTING2 = "functions/filename/stills/usersetting2"
    NETWORKCONNECTION = "functions/networkconnection"
    NETWORKSETTING = "functions/networksetting"
    RECORDFUNCTIONS_SEPARATE = "functions/recordfunctions/separate"
    REGISTEREDNAME_ARTIST = "functions/registeredname/artist"
    REGISTEREDNAME_AUTHOR = "functions/registeredname/author"
    REGISTEREDNAME_COPYRIGHT = "functions/registeredname/copyright"
    REGISTEREDNAME_NICKNAME = "functions/registeredname/nickname"
    REGISTEREDNAME_OWNERNAME = "functions/registeredname/ownername"
    SCREENDIMMER = "functions/screendimmer"
    SENSORCLEANING = "functions/sensorcleaning"
    SSL_CACERT = "functions/ssl/cacert"
    SSL_SERVERCERT_COMMONNAME = "functions/ssl/servercert/commonname"
    VIEWFINDEROFF = "functions/viewfinderoff"
    WIFICONNECTION = "functions/wificonnection"
    WIFISETTING = "functions/wifisetting"
    WIFISETTING_SET1 = "functions/wifisetting/set1"
    WIFISETTING_SET2 = "functions/wifisetting/set2"
    WIFISETTING_SET3 = "functions/wifisetting/set3"
    AF = "shooting/control/af"
    AF_POWERZOOM = "shooting/control/af/powerzoom"
    DRIVEFOCUS = "shooting/control/drivefocus"
    FLICKERDETECTION = "shooting/control/flickerdetection"
    HFFLICKERDETECTION = "shooting/control/hfflickerdetection"
    HFFLICKERTV = "shooting/control/hfflickertv"
    IGNORESHOOTINGMODEDIALMODE = "shooting/control/ignoreshootingmodedialmode"
    MOVIEMODE = "shooting/control/moviemode"
    POWERZOOM = "shooting/control/powerzoom"
    RECBUTTON = "shooting/control/recbutton"
    SHUTTERBUTTON = "shooting/control/shutterbutton"
    SHUTTERBUTTON_MANUAL = "shooting/control/shutterbutton/manual"
    ZOOM = "shooting/control/zoom"
    RECORDABLE = "shooting/information/recordable"
    LIVEVIEW = "shooting/liveview"
    LIVEVIEW_AFFRAMEPOSITION = "shooting/liveview/afframeposition"
    LIVEVIEW_ANGLEINFORMATION = "shooting/liveview/angleinformation"
    LIVEVIEW_CLICKWB = "shooting/liveview/clickwb"
    LIVEVIEW_FLIP = "shooting/liveview/flip"
    LIVEVIEW_FLIPDETAIL = "shooting/liveview/flipdetail"
    LIVEVIEW_MULTIPART = "shooting/liveview/multipart"
    LIVEVIEW_RTP = "shooting/liveview/rtp"
    LIVEVIEW_RTPSESSIONDESC = "shooting/liveview/rtpsessiondesc"
    LIVEVIEW_SCROLL = "shooting/liveview/scroll"
    LIVEVIEW_SCROLLDETAIL = "shooting/liveview/scrolldetail"
    SETTINGS = "shooting/settings"


@dataclass(frozen=True, slots=True)
class Resource:
    feature: str
    path: str
    version: str
    methods: Methods

    def allows(self, method: Methods) -> bool:
        return method in self.methods


# Endpoints that answer only when something happens, so a plain GET holds the
# link until it does. Everything here is opened with `stream=True` or not at all.
STREAMED = frozenset(
    {
        Endpoint.MONITORING,
        Endpoint.LIVEVIEW_MULTIPART,
        Endpoint.LIVEVIEW_SCROLLDETAIL,
    }
)


TABLE: dict[str, Volatility] = {
    Endpoint.DEVICEINFORMATION: Volatility.CONSTANT,
    Endpoint.LENS: Volatility.CONSTANT,
    Endpoint.BATTERY: Volatility.VOLATILE,
    Endpoint.BATTERYLIST: Volatility.VOLATILE,
    Endpoint.TEMPERATURE: Volatility.VOLATILE,
    Endpoint.STORAGE: Volatility.VOLATILE,
    Endpoint.CURRENTSTORAGE: Volatility.VOLATILE,
    Endpoint.CURRENTDIRECTORY: Volatility.VOLATILE,
    Endpoint.RELEASECOUNT: Volatility.VOLATILE,
    Endpoint.RECORDABLE: Volatility.VOLATILE,
    Endpoint.MOVIEMODE: Volatility.OWNED,
    Endpoint.AUTOPOWEROFF: Volatility.OWNED,
    Endpoint.DATETIME: Volatility.OWNED,
    Endpoint.REGISTEREDNAME_AUTHOR: Volatility.OWNED,
    Endpoint.REGISTEREDNAME_COPYRIGHT: Volatility.OWNED,
    Endpoint.REGISTEREDNAME_OWNERNAME: Volatility.OWNED,
    Endpoint.REGISTEREDNAME_NICKNAME: Volatility.OWNED,
}


def volatility_of(feature: str) -> Volatility:
    return TABLE.get(feature, Volatility.VOLATILE)


def suffix_of(path: str) -> tuple[str, str]:
    parts = [part for part in path.split("/") if part]
    if API_ROOT in parts:
        parts = parts[parts.index(API_ROOT) + 1 :]
    if not parts:
        return "", ""
    return parts[0], "/".join(parts[1:])


def methods_of(entry: dict[str, object]) -> Methods:
    found = Methods(0)
    for name, flag in (
        ("get", Methods.GET),
        ("post", Methods.POST),
        ("put", Methods.PUT),
        ("delete", Methods.DELETE),
    ):
        if entry.get(name):
            found |= flag
    return found


class Registry:
    def __init__(self, accepted_version: str | None = None) -> None:
        self.accepted_version = accepted_version
        self._resources: dict[str, Resource] = {}
        self._versions: set[str] = set()
        self._declined: set[str] = set()

    def clear(self) -> None:
        self._resources.clear()
        self._versions.clear()
        self._declined.clear()

    def load(self, manifest: dict[str, object]) -> None:
        self.clear()
        for version, entries in manifest.items():
            if not isinstance(entries, list):
                continue
            if self.accepted_version and version > self.accepted_version:
                self._declined.add(version)
                continue
            self._versions.add(version)
            for entry in entries:
                if isinstance(entry, dict):
                    self._absorb(version, entry)

    def _absorb(self, version: str, entry: dict[str, object]) -> None:
        path = str(entry.get("path", ""))
        found, feature = suffix_of(path)
        if not feature:
            return
        version = found or version
        methods = methods_of(entry)
        standing = self._resources.get(feature)
        if standing is None:
            self._resources[feature] = Resource(feature, path, version, methods)
            return
        if version > standing.version:
            self._resources[feature] = Resource(
                feature, path, version, methods | standing.methods
            )
        else:
            self._resources[feature] = Resource(
                standing.feature,
                standing.path,
                standing.version,
                standing.methods | methods,
            )

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(sorted(self._versions))

    @property
    def offered_beyond_accepted(self) -> tuple[str, ...]:
        return tuple(sorted(self._declined))

    @property
    def features(self) -> tuple[str, ...]:
        return tuple(sorted(self._resources))

    @property
    def loaded(self) -> bool:
        return bool(self._resources)

    def offers(self, feature: str) -> bool:
        return str(feature) in self._resources

    def resource_for(self, feature: str) -> Resource:
        from portable.ccapi.errors import FeatureMissingError

        found = self._resources.get(str(feature))
        if found is None:
            raise FeatureMissingError(f"the camera does not offer {feature!r}", 404)
        return found

    def path_for(self, feature: str) -> str:
        return self.resource_for(feature).path

    def methods_for(self, feature: str) -> Methods:
        return self.resource_for(feature).methods

    def unnamed(self, known: set[str]) -> tuple[str, ...]:
        return tuple(sorted(set(self._resources) - known))
