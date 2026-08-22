from build123d import Part, Plane, Polygon, Pos, extrude

from mounts.side_panel import CUT_OVERSHOOT, SidePanelFacing, SidePanelMount

CUTOUT_WIDTH = 10.0
CUTOUT_HEIGHT = 28.0
CUTOUT_BOTTOM = 1.0


class RockerSwitchMount(SidePanelMount):
    CHANNEL_LENGTH = 15.0
    CHANNEL_WIDTH = CUTOUT_WIDTH
    CHANNEL_HEIGHT = 30.0

    CLAMP_POINTS = ()

    STEP_SPANS = ()

    def _cutout_solid(self) -> Part:
        depth = self.panel_thickness + 2 * CUT_OVERSHOOT
        half_width = CUTOUT_WIDTH / 2
        top = CUTOUT_BOTTOM + CUTOUT_HEIGHT

        profile = Plane.YZ * Polygon(
            (-half_width, CUTOUT_BOTTOM),
            (half_width, CUTOUT_BOTTOM),
            (half_width, top),
            (-half_width, top),
            align=None,
        )
        return Pos(-(self.panel_thickness + CUT_OVERSHOOT), 0.0, 0.0) * extrude(
            profile, depth
        )

    def _retention_ribs(self) -> Part:
        return Part()


def sample() -> Part:
    return RockerSwitchMount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_POS,
        panel_thickness=3.0,
    ).sample()
