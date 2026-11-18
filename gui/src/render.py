"""Jinja filters and globals: how a value is written on the screen."""

import base64
import json
import time
from typing import Any

from gui.src import view
from shared.diagnostics import RunView, TestView
from shared.subsystem import Result, truthy


def clock(seconds: float | None) -> str:
    if not seconds:
        return ""
    whole = time.strftime("%H:%M:%S", time.localtime(seconds))
    return f"{whole}.{int((seconds % 1) * 1000):03d}"


def hex32(value: Any) -> str:
    return "0x" + format(int(value or 0) & 0xFFFFFFFF, "08X")


def bitset(value: Any, bit: Any) -> bool:
    return bool(int(value or 0) & int(bit or 0))


def hexnote(value: Any) -> str:
    text = "".join(str(value or "").split()).removeprefix("0x")
    if not text:
        return "0 bytes"
    if any(one not in "0123456789abcdefABCDEF" for one in text):
        return "Not valid hexadecimal"
    return f"{-(-len(text) // 2)} bytes"


def hexdump(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex(" ")
    return str(value or "")


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def data_uri(value: Any) -> str:
    """Return image bytes as a source an `img` tag can use directly."""
    if not isinstance(value, bytes) or not value:
        return ""
    kind = "png" if value.startswith(PNG_MAGIC) else "jpeg"
    return f"data:image/{kind};base64,{base64.b64encode(value).decode()}"


def as_record(result: Result | None) -> str:
    """Return a result as the JSON its copy button puts on the clipboard."""
    if result is None:
        return "{}"
    copied: dict[str, Any] = {}
    if result.summary:
        copied["summary"] = result.summary
    if result.note:
        copied["note"] = result.note
    if result.raw:
        copied["raw"] = result.raw.hex(" ")
    if result.image:
        copied["image"] = f"{len(result.image)} bytes"
    if result.fields:
        copied["fields"] = dict(result.fields)
    if result.table:
        head = list(result.table.head)
        copied["table"] = [
            {head[i] if i < len(head) else str(i): cell for i, cell in enumerate(row)}
            for row in result.table.rows
        ]
    return json.dumps(copied, indent=2)


def as_run(test: TestView, subsystem_id: str) -> str:
    run: RunView | None = test.last
    if run is None:
        return "{}"
    return json.dumps(
        {
            "subsystem": subsystem_id,
            "test": test.key,
            "title": test.title,
            "status": view.status_of(test),
            "when": clock(run.started) or None,
            "inputs": _plain(run.values),
            "steps": [
                {
                    "step": settled.step,
                    "status": settled.status.value,
                    **({"skipped": settled.skipped.value} if settled.skipped else {}),
                    **({"detail": settled.detail} if settled.detail else {}),
                    **(
                        {
                            "measurements": [
                                {
                                    "name": one.name,
                                    "value": one.value,
                                    "unit": one.unit,
                                    "limits": one.limits() or None,
                                    "within": one.within,
                                }
                                for one in settled.measurements
                            ]
                        }
                        if settled.measurements
                        else {}
                    ),
                    **({"answers": dict(settled.answers)} if settled.answers else {}),
                    **(
                        {"result": json.loads(as_record(settled.result))}
                        if settled.result
                        else {}
                    ),
                }
                for settled in run.outcomes
            ],
        },
        indent=2,
        default=str,
    )


def _plain(values: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value.hex(" ") if isinstance(value, bytes) else value
        for name, value in values.items()
    }


FILTERS = {
    "clock": clock,
    "slug": view.slug,
    "truthy": truthy,
    "hex32": hex32,
    "bitset": bitset,
    "hexnote": hexnote,
    "hexdump": hexdump,
    "data_uri": data_uri,
    "as_record": as_record,
    "as_run": as_run,
}

GLOBALS = {
    "OUTCOME": view.OUTCOME,
    "LINK_MARK": view.LINK_MARK,
    "LEVEL_TONE": view.LEVEL_TONE,
    "DETAIL_TONE": view.DETAIL_TONE,
    "STATUS_LABEL": view.STATUS_LABEL,
    "LINK_LABEL": view.LINK_LABEL,
    "SKIPPED_BECAUSE": view.SKIPPED_BECAUSE,
    "TOOLS": view.TOOLS,
    "TOOL_LABEL": view.TOOL_LABEL,
    "TOOL_ICON": view.TOOL_ICON,
    "group_label": view.group_label,
    "end_errored": view.end_errored,
    "stop_patience": view.stop_patience,
    "stop_waited": view.stop_waited,
    "rows_of": view.rows_of,
    "status_of": view.status_of,
    "worst_status": view.worst_status,
}

__all__ = ["FILTERS", "GLOBALS"]
