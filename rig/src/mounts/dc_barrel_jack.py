from build123d import (
    Circle,
    Part,
    Plane,
    Polygon,
    Pos,
    extrude,
    mirror,
)

from mounts.side_panel import (
    CUT_OVERSHOOT,
    SidePanelFacing,
    SidePanelMount,
    as_part,
)

BARREL_RIB_LENGTH = 8.5
CHAMFER_LENGTH = 3.0
PLAIN_LENGTH = 18.0
TERMINAL_RIB_LENGTH = 3.5

RIB_INSET = 1.5
STEP_HEIGHT = 1.5

CUTOUT_DIAMETER = 8.0
CUTOUT_CENTRE_HEIGHT = 6.0


class DCBarrelJackMount(SidePanelMount):
    CHANNEL_LENGTH = (
        BARREL_RIB_LENGTH + CHAMFER_LENGTH + PLAIN_LENGTH + TERMINAL_RIB_LENGTH
    )
    CHANNEL_WIDTH = 13.5
    CHANNEL_HEIGHT = 12.0

    CLAMP_POINTS = ((12.0, 12.0),)

    STEP_SPANS = (
        (0.0, BARREL_RIB_LENGTH, STEP_HEIGHT),
        (CHANNEL_LENGTH - TERMINAL_RIB_LENGTH, TERMINAL_RIB_LENGTH, STEP_HEIGHT),
    )

    def _cutout_solid(self) -> Part:
        depth = self.panel_thickness + 2 * CUT_OVERSHOOT
        profile = (
            Plane.YZ * Pos(0.0, CUTOUT_CENTRE_HEIGHT) * Circle(CUTOUT_DIAMETER / 2)
        )
        return Pos(-(self.panel_thickness + CUT_OVERSHOOT), 0.0, 0.0) * extrude(
            profile, depth
        )

    def _retention_ribs(self) -> Part:
        wall_face = self.CHANNEL_WIDTH / 2
        rib_face = wall_face - RIB_INSET

        barrel = extrude(
            Polygon(
                (0.0, rib_face),
                (BARREL_RIB_LENGTH, rib_face),
                (BARREL_RIB_LENGTH + CHAMFER_LENGTH, wall_face),
                (0.0, wall_face),
                align=None,
            ),
            self.CHANNEL_HEIGHT,
        )
        return as_part(barrel + mirror(barrel, Plane.XZ))


def sample() -> Part:
    return DCBarrelJackMount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_POS,
        panel_thickness=3.0,
    ).sample()
