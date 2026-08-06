"""The firmware's API as the PC sees it: the ABI, and the surface it implies."""

from typing import Any

from shared.fw_api import api


def __getattr__(name: str) -> Any:
    """Relay every name to the surface, which relays what it does not define."""
    return getattr(api, name)


def __dir__() -> list[str]:
    """Return everything the surface and the ABI beneath it carry."""
    return sorted({*globals(), *dir(api)})
