"""One fixture subsystem, loaded once, and a registry that survives being written to."""

import pytest

from shared import bench_api

FIXTURE = "shared.bench_api.tests.fixture"


@pytest.fixture(scope="session", autouse=True)
def loaded():
    """Import the fixture package once, the way a backend would."""
    bench_api.load(FIXTURE)
    return bench_api.REGISTRY


@pytest.fixture
def rig(loaded):
    """Return the fixture subsystem."""
    return loaded.subsystem("rig")


@pytest.fixture
def declaring(loaded):
    """Return a way to run a module body, undoing whatever it registered."""
    rig = loaded.subsystem("rig")
    before = (dict(rig.bench_tests), dict(rig.actions), rig.link)

    def declare(body, module=f"{FIXTURE}.declared"):
        namespace = {"__name__": module, "bench_api": bench_api}
        exec(compile(body, module, "exec"), namespace)
        return namespace

    yield declare

    rig.bench_tests, rig.actions, rig.link = (
        before[0],
        before[1],
        before[2],
    )
