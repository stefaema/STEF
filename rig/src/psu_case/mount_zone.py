from dataclasses import dataclass
from enum import Enum, auto


class Axis(Enum):
    X = auto()
    Y = auto()


@dataclass(frozen=True)
class Spacer:
    axis: Axis


SPACER_X = Spacer(axis=Axis.X)
SPACER_Y = Spacer(axis=Axis.Y)

Layout = tuple[float | Spacer, ...]


@dataclass(frozen=True)
class ResolvedLayout:
    spans: tuple[float, ...]
    offsets: tuple[float, ...]

    @property
    def centers(self) -> tuple[float, ...]:
        return tuple(
            offset + span / 2 for offset, span in zip(self.offsets, self.spans)
        )


def _minimum_span(layout: Layout) -> float:
    return sum(item for item in layout if not isinstance(item, Spacer))


def _resolve(items: Layout, total_span: float) -> ResolvedLayout:
    fixed_total = _minimum_span(items)
    spacer_count = sum(1 for item in items if isinstance(item, Spacer))
    flex = (total_span - fixed_total) / spacer_count if spacer_count else 0.0

    spans = tuple(flex if isinstance(item, Spacer) else float(item) for item in items)
    offsets = []
    running = 0.0
    for span in spans:
        offsets.append(running)
        running += span
    return ResolvedLayout(spans=spans, offsets=tuple(offsets))


class MountZone:
    @staticmethod
    def get_minimum_width(front_panel_layout: Layout) -> float:
        return _minimum_span(front_panel_layout)

    @staticmethod
    def get_minimum_depth(
        distance_layout_3wago: Layout,
        distance_layout_5wago_pair: Layout,
    ) -> float:
        return max(
            _minimum_span(distance_layout_3wago),
            _minimum_span(distance_layout_5wago_pair),
        )

    @staticmethod
    def solve(
        front_panel_layout: Layout,
        distance_layout_3wago: Layout,
        distance_layout_5wago_pair: Layout,
        *,
        structure_width: float,
        structure_depth: float,
        front_panel_thickness: float,  # aka front wall thickness
        case_wall_thickness: float,  # side and back walls only
    ) -> dict[str, ResolvedLayout]:
        usable_width = structure_width - 2 * case_wall_thickness
        usable_depth = structure_depth - front_panel_thickness - case_wall_thickness

        minimum_width = MountZone.get_minimum_width(front_panel_layout)
        if usable_width < minimum_width:
            raise ValueError(
                f"usable width {usable_width} is below the row's minimum {minimum_width}"
            )

        return {
            "front_panel": _resolve(front_panel_layout, usable_width),
            "wago_3": _resolve(distance_layout_3wago, usable_depth),
            "wago_5_pair": _resolve(distance_layout_5wago_pair, usable_depth),
        }
