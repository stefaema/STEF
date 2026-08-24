from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from shared.bench_api import Input, coerced_values

TRUTHY = ("true", "1", "on", "yes")


def values_from(inputs: Sequence[Input], form: Mapping[str, Any]) -> dict[str, Any]:
    return coerced_values(inputs, _submitted(inputs, form))


def _submitted(inputs: Sequence[Input], form: Mapping[str, Any]) -> dict[str, Any]:
    taken: dict[str, Any] = {}
    for item in inputs:
        if item.kind == "group":
            taken[item.name] = _rows(item, form)
        elif item.kind == "bitmask":
            taken[item.name] = _mask(item.name, form)
        elif item.kind == "boolean":
            taken[item.name] = _flag(item.name, form)
        elif item.name in form:
            taken[item.name] = form[item.name]
    return taken


def _listed(name: str, form: Mapping[str, Any]) -> list[Any]:
    getter = getattr(form, "getlist", None)
    if getter is not None:
        return list(getter(name))
    found = form.get(name)
    if found is None:
        return []
    return list(found) if isinstance(found, list) else [found]


def _flag(name: str, form: Mapping[str, Any]) -> bool:
    return str(form.get(name, "")).strip().lower() in TRUTHY


def _mask(name: str, form: Mapping[str, Any]) -> int:
    held = 0
    for one in _listed(name, form):
        held |= int(one or 0)
    return held


def _rows(item: Input, form: Mapping[str, Any]) -> list[dict[str, Any]]:
    prefix = f"{item.name}."
    indices = sorted(
        {
            key[len(prefix) :].partition(".")[0]
            for key in form
            if key.startswith(prefix)
        },
        key=_ordinal,
    )
    return [_row(item, form, f"{prefix}{index}.") for index in indices]


def _row(item: Input, form: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    return _submitted(item.columns, _Scoped(form, prefix))


def _ordinal(index: str) -> int:
    return int(index) if index.isdigit() else 0


class _Scoped(Mapping[str, Any]):
    def __init__(self, form: Mapping[str, Any], prefix: str) -> None:
        self._form = form
        self._prefix = prefix

    def __getitem__(self, key: str) -> Any:
        return self._form[self._prefix + key]

    def __iter__(self):
        for key in self._form:
            if key.startswith(self._prefix):
                yield key[len(self._prefix) :]

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def getlist(self, key: str) -> list[Any]:
        getter = getattr(self._form, "getlist", None)
        if getter is not None:
            return list(getter(self._prefix + key))
        return (
            [self._form[self._prefix + key]] if self._prefix + key in self._form else []
        )


__all__ = ["values_from"]
