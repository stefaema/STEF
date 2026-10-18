import pytest

import demo
from demo.bench import link


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(link, "PACE_S", 0.0)


@pytest.fixture
def board():
    found = demo.SUBSYSTEM(demo)
    found.connect("healthy")
    yield found
    found.disconnect()
