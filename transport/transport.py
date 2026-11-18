"""What the transport's port is called, and how a link to it is opened."""

from typing import Any

from shared import fw_api
from transport import fw

AUTO = "auto"


# ── What is on the far end ───────────────────────────────────────────────────


def named_port(port: str) -> str | None:
    """Return the port the operator chose, or None where they left the choice open."""
    return None if port == AUTO else port


def text(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    return str(raw)


# ── The link ─────────────────────────────────────────────────────────────────


def opened(port: str) -> fw.link.FirmwareLink:
    chosen = fw.probe.find_port(named_port(port))
    link = fw.link.FirmwareLink(chosen, on_log=fw.logs.forward)
    try:
        reply = link.sys.version()
        backend, version = text(reply.backend), text(reply.version)
        if not fw_api.compatible(backend, version):
            raise fw.link.LinkError(
                f"the board is {backend} {version} and this build speaks "
                f"{fw_api.FW_API_BACKEND} {fw_api.FW_API_VERSION}. Flash it"
            )
    except Exception:
        link.close()
        raise
    return link
