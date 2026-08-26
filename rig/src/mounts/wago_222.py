from build123d import (
    Align,
    Box,
    Part,
    Plane,
    Polygon,
    Pos,
    Rot,
    Vector,
    extrude,
    mirror,
)

from mounts.side_panel import SidePanelFacing, as_part

STEP_RISE = 3.5
STEP_RUN = 6.0


class Wago222Mount:
    CHANNEL_LENGTH = 20.0
    CHANNEL_HEIGHT = 7.0

    CLAMP_POINTS: tuple[tuple[float, float], ...] = ()

    STEP_SPANS = ((CHANNEL_LENGTH, 1.0, 1.0),)

    def __init__(
        self,
        at: tuple[float, float, float],
        facing: SidePanelFacing,
        channel_width: float,
        sidewall_thickness: float = 2.0,
    ) -> None:
        self.CHANNEL_WIDTH = channel_width
        self.sidewall_thickness = sidewall_thickness
        self._placement = Pos(*at) * Rot(0.0, 0.0, facing.z_rotation)

    def _sidewalls(self) -> Part:
        closing = Pos(-self.sidewall_thickness, 0.0, 0.0) * Box(
            self.sidewall_thickness,
            self.CHANNEL_WIDTH + 2 * self.sidewall_thickness,
            self.CHANNEL_HEIGHT,
            align=(Align.MIN, Align.CENTER, Align.MIN),
        )
        flank = Pos(0.0, self.CHANNEL_WIDTH / 2, 0.0) * Box(
            self.CHANNEL_LENGTH,
            self.sidewall_thickness,
            self.CHANNEL_HEIGHT,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        return as_part(closing + flank + mirror(flank, Plane.XZ))

    def _levelling_steps(self) -> Part:
        profile = Plane.XZ * Polygon(
            (0.0, 0.0),
            (STEP_RUN, 0.0),
            (0.0, STEP_RISE),
            align=None,
        )
        steps = Pos(0.0, self.CHANNEL_WIDTH / 2, 0.0) * extrude(
            profile, self.CHANNEL_WIDTH
        )
        span = self.CHANNEL_WIDTH + 2 * self.sidewall_thickness
        for start, length, height in self.STEP_SPANS:
            steps += Pos(start, 0.0, 0.0) * Box(
                length,
                span,
                height,
                align=(Align.MIN, Align.CENTER, Align.MIN),
            )
        return steps

    def body(self) -> Part:
        return self._placement * as_part(self._sidewalls() + self._levelling_steps())

    def clamp_points(self) -> list[Vector]:
        return [
            (self._placement * Pos(x, 0.0, height)).position
            for x, height in self.CLAMP_POINTS
        ]

    def sample(self, floor_thickness: float = 2.0) -> Part:
        body = self._sidewalls() + self._levelling_steps()
        bounds = body.bounding_box()
        floor = Pos(bounds.min.X, bounds.min.Y, -floor_thickness) * Box(
            bounds.size.X,
            bounds.size.Y,
            floor_thickness,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        return as_part(floor + body)


CHANNEL_WIDTH_5CABLE = 26.0
CHANNEL_WIDTH_3CABLE = 17.0


def sample() -> dict[str, Part]:
    return {
        "5cable": Wago222Mount(
            at=(0.0, 0.0, 0.0),
            facing=SidePanelFacing.X_POS,
            channel_width=CHANNEL_WIDTH_5CABLE,
        ).sample(),
        "3cable": Wago222Mount(
            at=(0.0, 0.0, 0.0),
            facing=SidePanelFacing.X_POS,
            channel_width=CHANNEL_WIDTH_3CABLE,
        ).sample(),
    }
