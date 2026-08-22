import pytest

from machine import assembled
from machine.tests import fixture
from shared import bench_api
from shared.subsystem import SubsystemState

FIXTURE = "machine.tests.fixture"


@pytest.fixture(scope="session")
def hotplate():
    bench_api.REGISTRY.clear()
    yield assembled(FIXTURE)
    bench_api.REGISTRY.clear()


@pytest.fixture
def plugged_in(hotplate):
    fixture.set_state(SubsystemState.UP)
    yield hotplate
    fixture.set_state(SubsystemState.DOWN)
