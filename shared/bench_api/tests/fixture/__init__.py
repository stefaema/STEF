"""A subsystem that exists only to be declared against.

A real package, so the walk from a declaration's module up to its subsystem has
something real to walk.
"""

from shared.bench_api.tests.fixture.subsystem import Rig, RigLink

__all__ = ["Rig", "RigLink"]
