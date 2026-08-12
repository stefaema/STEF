"""Every legend the browser writes, in one place, in Python.

The screen builds most of itself in JavaScript, so most legends would live there
and be invisible to an extractor that reads Python. Splitting the catalog across
two languages means two extraction toolchains and two places to forget.

They are all declared here instead and handed over with the page. The browser
holds only keys, so nothing there is a translatable string, and `xgettext` over
the Python sources sees the whole catalog.
"""

from __future__ import annotations

from typing import Any

from gui.src.i18n import gettext as _


def catalog() -> dict[str, Any]:
    """Return every legend, translated, in the shape the browser looks them up by."""
    return {
        "subsystem": {
            "transport": _("Transport"),
            "capture": _("Capture"),
            "detect": _("Detection"),
        },
        "card": {
            "implementation": _("Implementation"),
            "connection": _("Connection"),
            "before": _("Before connecting"),
            "unavailable": _("This part is not built yet"),
        },
        "tool": {
            "link": _("Link"),
            "checks": _("Bench tests"),
            "actions": _("Actions"),
            "before": _("Before connecting"),
        },
        "link": {
            "connect": _("Connect"),
            "disconnect": _("Disconnect"),
            "connecting": _("Connecting"),
            "refresh": _("Refresh"),
            "blocked": _("Cannot connect"),
            "form": _("Connection"),
            "state": {
                "down": _("Not linked"),
                "linking": _("Linking"),
                "up": _("Linked"),
                "error": _("Failed"),
            },
        },
        "status": {
            "idle": _("Not run"),
            "running": _("Running"),
            "passed": _("Passed"),
            "warned": _("Warnings"),
            "failed": _("Failed"),
            "skipped": _("Skipped"),
        },
        "run": {
            "run": _("Run"),
            "rerun": _("Run again"),
            "running": _("Running"),
            "arm": _("Arm"),
            "confirm": _("Confirm"),
            "hazardous": _("Hazardous"),
            "needs_link": _("Connect first"),
            "refused": _("Refused"),
            "steps": _("Steps"),
            "none": _("This subsystem declares no bench tests"),
        },
        "action": {
            "run": _("Run"),
            "namespace": _("Namespace"),
            "method": _("Method"),
            "arguments": _("Arguments"),
            "no_arguments": _("This method takes no arguments"),
            "none": _("This subsystem declares no actions"),
            "reply": _("Reply"),
            "blocked": _("Not available"),
            "add_row": _("Add row"),
            "remove_row": _("Remove"),
            "invalid_hex": _("Not valid hexadecimal"),
            "bytes": _("bytes"),
            "range": _("Range"),
        },
        "log": {
            "pause": _("Pause"),
            "resume": _("Resume"),
            "clear": _("Clear"),
            "export": _("Export"),
            "all": _("All"),
            "empty": _("Nothing logged yet"),
        },
        "misc": {
            "busy": _("The machine is busy"),
            "disconnected": _("Lost the event stream, retrying"),
            "unavailable": _("No control declared for this"),
            "protocol": _("Protocol"),
            "more": _("Show more"),
            "less": _("Show less"),
        },
    }
