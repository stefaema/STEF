import pytest

from shared import bench_api
from shared.subsystem import SubsystemSpec

TRANSPORT = bench_api.derive(SubsystemSpec.of_package("transport"))


@pytest.fixture(scope="session")
def declared():
    """Return the subsystem, loaded once before any test module was imported."""
    return TRANSPORT
