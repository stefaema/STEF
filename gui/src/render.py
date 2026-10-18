from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any

from gui.src import view
from shared.diagnostics import RunView, TestView
from shared.subsystem import Result

TRUTHY = (True, 1, "true", "1", "on", "yes")


class OptionsCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    def warm(self, subsystem: str, key: str, name: str) -> list[dict[str, Any]] | None:
        with self._lock:
            return self._held.get((subsystem, key, name))

    def fetch(
        self, sub: Any, key: str, name: str, refresh: bool = False
    ) -> list[dict[str, Any]]:
        if not refresh:
            found = self.warm(sub.id, key, name)
            if found is not None:
                return found
        listed = list(sub.options(key, name))
        with self._lock:
            self._held[(sub.id, key, name)] = listed
        return listed

    def forget(self, subsystem: str | None = None) -> None:
        with self._lock:
            if subsystem is None:
                self._held.clear()
                return
            for one in [k for k in self._held if k[0] == subsystem]:
                del self._held[one]


OPTIONS = OptionsCache()


def clock(seconds: float | None) -> str:
    if not seconds:
        return ""
    whole = time.strftime("%H:%M:%S", time.localtime(seconds))
    return f"{whole}.{int((seconds % 1) * 1000):03d}"


def slug(text: Any) -> str:
    return str(text).replace(".", "-").replace("/", "-")


def truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "on", "yes")
    return bool(value)


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


def as_record(answer: Result | None) -> str:
    if answer is None:
        return "{}"
    packed: dict[str, Any] = {}
    if answer.summary:
        packed["summary"] = answer.summary
    if answer.note:
        packed["note"] = answer.note
    if answer.raw:
        packed["raw"] = answer.raw.hex(" ")
    if answer.image:
        packed["image"] = f"{len(answer.image)} bytes"
    if answer.fields:
        packed["fields"] = dict(answer.fields)
    if answer.table:
        head = list(answer.table.head)
        packed["table"] = [
            {head[i] if i < len(head) else str(i): cell for i, cell in enumerate(row)}
            for row in answer.table.rows
        ]
    return json.dumps(packed, indent=2)


def as_run(test: TestView, subsystem: str) -> str:
    run: RunView | None = test.last
    if run is None:
        return "{}"
    return json.dumps(
        {
            "subsystem": subsystem,
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


def field_of(spec: Any, sub_id: str, key: str) -> view.Field:
    return view.fields_of((spec,), OPTIONS.warm, sub_id, key)[0]


FILTERS = {
    "clock": clock,
    "slug": slug,
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
    "field_of": field_of,
    "group_label": view.group_label,
    "end_errored": view.end_errored,
    "rows_of": view.rows_of,
    "status_of": view.status_of,
    "worst_status": view.worst_status,
}

__all__ = ["FILTERS", "GLOBALS", "OPTIONS", "OptionsCache"]
