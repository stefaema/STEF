from build123d import Part, Plane, Polygon, Pos, extrude

from mounts.side_panel import CUT_OVERSHOOT, SidePanelFacing, SidePanelMount
from rig.materials import Material

ENGAGEMENT_DEPTH = 5.0
STEP_GAP = 26.0

PANEL_STEP_HEIGHT = 4.0
FAR_STEP_LENGTH = 2.0
FAR_STEP_HEIGHT = 2.0


CUTOUT_WIDTH = {Material.PLA: 14.5, Material.PETG: 14.5 * 1.02}
CUTOUT_HEIGHT = {Material.PLA: 16.0, Material.PETG: 16.0 * 1.02}
CUTOUT_BOTTOM = 4.0


class RJ45KeystoneMount(SidePanelMount):
    CHANNEL_WIDTH = 17.0
    CHANNEL_HEIGHT = 20.0  # temp, check: needs a printed iteration to confirm

    CLAMP_POINTS = ()  # temp, check: needs a printed iteration to confirm

    def __init__(
        self,
        at: tuple[float, float, float],
        facing: SidePanelFacing,
        panel_thickness: float,
        material: Material = Material.PLA,
        sidewall_thickness: float = 2.0,
    ) -> None:
        super().__init__(at, facing, panel_thickness, sidewall_thickness)
        self.material = material

        uncovered = max(0.0, ENGAGEMENT_DEPTH - panel_thickness)
        far = (uncovered + STEP_GAP, FAR_STEP_LENGTH, FAR_STEP_HEIGHT)
        panel_step = (0.0, uncovered, PANEL_STEP_HEIGHT)
        self.STEP_SPANS = (panel_step, far) if uncovered else (far,)
        self.CHANNEL_LENGTH = uncovered + STEP_GAP + FAR_STEP_LENGTH

    def _cutout_solid(self) -> Part:
        depth = self.panel_thickness + 2 * CUT_OVERSHOOT
        half_width = CUTOUT_WIDTH[self.material] / 2
        top = CUTOUT_BOTTOM + CUTOUT_HEIGHT[self.material]

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


def sample(material: Material = Material.PLA) -> Part:
    return RJ45KeystoneMount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_POS,
        panel_thickness=3.0,
        material=material,
    ).sample()
