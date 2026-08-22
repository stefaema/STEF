import importlib

import pytest

from shared import bench_api
from shared.bench_api import SubsystemLinkState
from shared.subsystem import SubsystemSpec

FIXTURE = "shared.bench_api.tests.fixture"


@pytest.fixture(scope="session")
def oven():
    """Return the fixture subsystem, loaded once.

    A declaration runs when its module is imported, so loading is a
    once-per-process act and a fixture that reloaded would register a subsystem
    with no routines under it.
    """
    bench_api.REGISTRY.clear()
    yield bench_api.derive(SubsystemSpec.of(importlib.import_module(FIXTURE)))
    bench_api.REGISTRY.clear()


@pytest.fixture
def linked(oven):
    """Return the same subsystem, with its link up for the length of one test."""
    from shared.bench_api.tests.fixture import hardware

    hardware.set_link_state(SubsystemLinkState.UP)
    yield oven
    hardware.set_link_state(SubsystemLinkState.DOWN)
