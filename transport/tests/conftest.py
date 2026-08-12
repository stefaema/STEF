import pytest

from shared import bench_api

TRANSPORT = bench_api.load_subsystem("transport")


@pytest.fixture(scope="session")
def declared():
    """Return the subsystem, loaded once before any test module was imported."""
    return TRANSPORT
