"""One vocabulary three unrelated subsystems speak, so one screen renders declarations.

The subsystem declares what only it can know; everything else is the GUI's. A
declaration imports this package and this package imports nothing back: no I/O,
no third-party dependency, no subsystem, and no ctypes.
"""

from shared.bench_api.decorators import (
    action,
    bench_test,
    link,
    link_test,
    step,
    subsystem,
)
from shared.bench_api.derive import DerivationError, params_for, with_declared
from shared.bench_api.digest import Button, Digest, Layer, Span
from shared.bench_api.events import Event
from shared.bench_api.params import (
    Kind,
    Param,
    bitmask,
    boolean,
    choice,
    group,
    integer,
    raw_bytes,
)
from shared.bench_api.readiness import READY, Readiness, blocked
from shared.bench_api.registry import (
    REGISTRY,
    Action,
    BenchTest,
    DeclarationError,
    Link,
    Registry,
    Step,
    Subsystem,
    load,
)
from shared.bench_api.results import Outcome, Result, Table
from shared.bench_api.state import SEVERITY, Level, Status, SubsystemState, worst

__all__ = [
    "READY",
    "REGISTRY",
    "SEVERITY",
    "Action",
    "BenchTest",
    "Button",
    "DeclarationError",
    "DerivationError",
    "Digest",
    "Event",
    "Kind",
    "Layer",
    "Level",
    "Link",
    "Outcome",
    "Param",
    "Readiness",
    "Registry",
    "Result",
    "Span",
    "Status",
    "Step",
    "Subsystem",
    "SubsystemState",
    "Table",
    "action",
    "bench_test",
    "bitmask",
    "blocked",
    "boolean",
    "choice",
    "group",
    "integer",
    "link",
    "link_test",
    "load",
    "params_for",
    "raw_bytes",
    "step",
    "subsystem",
    "with_declared",
    "worst",
]
