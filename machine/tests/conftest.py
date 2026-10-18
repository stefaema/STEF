import pytest

from machine import assembled

FIXTURE = "machine.tests.fixture"


@pytest.fixture
def hotplate():
    return assembled(FIXTURE)


@pytest.fixture
def plugged_in(hotplate):
    hotplate.connect("low")
    yield hotplate
    hotplate.disconnect()
