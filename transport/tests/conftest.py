from types import SimpleNamespace

import pytest

import transport
from shared import fw_api
from shared.subsystem import READY


class Sys:
    def __init__(self, names=("capstan",)):
        self.names = names

    def devices(self):
        made = [
            SimpleNamespace(name=name.encode(), addr=index)
            for index, name in enumerate(self.names)
        ]
        return SimpleNamespace(devs=made)

    def version(self):
        return type(
            "Version",
            (),
            {
                "backend": fw_api.FW_API_BACKEND.encode(),
                "version": fw_api.FW_API_VERSION.encode(),
                "idf": b"v5.3",
            },
        )()


class Board:
    def __init__(self, raw, names=("capstan",)):
        self.raw = raw
        self.sys = Sys(names)
        self.alive = True
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def unlinked():
    return transport.SUBSYSTEM(transport)


@pytest.fixture
def linked_to(monkeypatch):
    def link(board):
        sub = transport.SUBSYSTEM(transport)
        monkeypatch.setattr(sub, "probe", lambda target: READY)
        monkeypatch.setattr(sub, "_open", lambda target: board)
        sub.connect("auto")
        return sub

    return link
