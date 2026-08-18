from build123d import (
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

RIB_LENGTH = 6.0
RIB_INSET = 4.0

STEP_HEIGHT = 2.0

CUTOUT_WIDTH = 25.5
CUTOUT_HEIGHT = 19.0
CUTOUT_BOTTOM = 1.0
CUTOUT_CHAMFER_RUN = 5.0
CUTOUT_CHAMFER_RISE = 7.0


class C14Mount(SidePanelMount):
    CHANNEL_LENGTH = 55.0
    CHANNEL_WIDTH = 27.5
    CHANNEL_HEIGHT = 22.0

    CLAMP_POINTS = ((10.0, 19.0), (50.0, 18.0))

    STEP_SPANS = ((25.0, 5.0, STEP_HEIGHT), (50.0, 5.0, STEP_HEIGHT))

    def _cutout_solid(self) -> Part:
        depth = self.panel_thickness + 2 * CUT_OVERSHOOT
        half_width = CUTOUT_WIDTH / 2
        top = CUTOUT_BOTTOM + CUTOUT_HEIGHT
        shoulder = top - CUTOUT_CHAMFER_RISE
        half_top = half_width - CUTOUT_CHAMFER_RUN

        profile = Plane.YZ * Polygon(
            (-half_width, CUTOUT_BOTTOM),
            (half_width, CUTOUT_BOTTOM),
            (half_width, shoulder),
            (half_top, top),
            (-half_top, top),
            (-half_width, shoulder),
            align=None,
        )
        return Pos(-(self.panel_thickness + CUT_OVERSHOOT), 0.0, 0.0) * extrude(
            profile, depth
        )

    def _retention_ribs(self) -> Part:
        wall_face = self.CHANNEL_WIDTH / 2
        taper_start = self.CHANNEL_LENGTH - RIB_LENGTH
        rib = extrude(
            Polygon(
                (self.CHANNEL_LENGTH, wall_face - RIB_INSET),
                (self.CHANNEL_LENGTH, wall_face),
                (taper_start, wall_face),
                align=None,
            ),
            self.CHANNEL_HEIGHT,
        )
        return as_part(rib + mirror(rib, Plane.XZ))


def sample() -> Part:
    return C14Mount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_POS,
        panel_thickness=3.0,
    ).sample()
