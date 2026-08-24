from __future__ import annotations

import json
import threading
import time
from typing import Any

from gui.src import view
from gui.src.runs import RUNS, RunState, address_of
from shared import bench_api
from shared.bench_api import Result, Routine

TRUTHY = (True, 1, "true", "1", "on", "yes")


class OptionsCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    def warm(self, subsystem: str, key: str, name: str) -> list[dict[str, Any]] | None:
        with self._lock:
            return self._held.get((subsystem, key, name))

    def fetch(
        self, subsystem: str, key: str, name: str, refresh: bool = False
    ) -> list[dict[str, Any]]:
        if not refresh:
            found = self.warm(subsystem, key, name)
            if found is not None:
                return found
        listed = bench_api.options_of(subsystem, key, name)
        with self._lock:
            self._held[(subsystem, key, name)] = listed
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
    if answer.fields:
        packed["fields"] = dict(answer.fields)
    if answer.table:
        head = list(answer.table.head)
        packed["table"] = [
            {head[i] if i < len(head) else str(i): cell for i, cell in enumerate(row)}
            for row in answer.table.rows
        ]
    return json.dumps(packed, indent=2)


def as_run(run: RunState, item: Routine, subsystem: str) -> str:
    titles = list(item.steps) or [f"#{i + 1}" for i in range(len(run.outcomes))]
    return json.dumps(
        {
            "subsystem": subsystem,
            "routine": f"{item.group}.{item.name}",
            "title": item.title,
            "status": run.status,
            "when": clock(run.when) or None,
            "inputs": _plain(run.values),
            "steps": [
                {
                    "step": titles[index] if index < len(titles) else f"#{index + 1}",
                    "status": settled.status.value,
                    **({"detail": settled.detail} if settled.detail else {}),
                    **(
                        {"result": json.loads(as_record(settled.value))}
                        if settled.value
                        else {}
                    ),
                }
                for index, settled in enumerate(run.outcomes)
            ],
        },
        indent=2,
    )


def _plain(values: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value.hex(" ") if isinstance(value, bytes) else value
        for name, value in values.items()
    }


def steps_of(item: Routine, run: RunState) -> list[tuple[str, Any, str]]:
    if item.steps:
        declared = [
            (title, run.settled_at(index)) for index, title in enumerate(item.steps)
        ]
    else:
        declared = [
            (f"#{index + 1}", settled) for index, settled in enumerate(run.outcomes)
        ]
    reached = sum(1 for _, settled in declared if settled is not None)
    settled_rows = []
    for index, (title, settled) in enumerate(declared):
        if settled is not None:
            status = settled.status.value
        elif run.running and index == reached:
            status = "running"
        else:
            status = "idle"
        settled_rows.append((title, settled, status))
    return settled_rows


def worst_of(items: list[Routine], subsystem: str) -> str:
    return RUNS.worst_under(
        [address_of(subsystem, f"{one.group}.{one.name}") for one in items]
    )


FILTERS = {
    "clock": clock,
    "slug": slug,
    "truthy": truthy,
    "hex32": hex32,
    "bitset": bitset,
    "hexnote": hexnote,
    "hexdump": hexdump,
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
    "TOOLS": view.TOOLS,
    "TOOL_LABEL": view.TOOL_LABEL,
    "TOOL_ICON": view.TOOL_ICON,
    "category_label": view.category_label,
    "steps_of": steps_of,
}

__all__ = ["FILTERS", "GLOBALS", "OPTIONS", "OptionsCache", "steps_of", "worst_of"]
