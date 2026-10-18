import pytest

from shared.diagnostics.tests import fixture
from shared.diagnostics.tests.fixture.oven import Oven


@pytest.fixture
def oven():
    found = Oven(fixture)
    found.connect("/dev/oven0")
    yield found
    found.disconnect()
