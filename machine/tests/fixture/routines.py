from collections.abc import Iterator

from shared import bench_api
from shared.bench_api import PASSED, StepOutcome


@bench_api.routine(category=bench_api.PRELINK, steps=("Warming",))
def warm(values: dict) -> Iterator[StepOutcome]:
    """Warm the element."""
    yield StepOutcome(PASSED, "warm")
