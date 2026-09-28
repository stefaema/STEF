from build123d import Part, Plane, Polygon, Pos, extrude

from mounts.side_panel import CUT_OVERSHOOT, SidePanelFacing, SidePanelMount
from rig.materials import Material

CUTOUT_WIDTH = {Material.PLA: 10.0, Material.PETG: 10.0 * 1.02}
CUTOUT_HEIGHT = {Material.PLA: 28.0, Material.PETG: 28.0 * 1.02}
CUTOUT_BOTTOM = 1.0

SAMPLE_CEILING = {Material.PLA: 2.0, Material.PETG: 4.0}
SIDEWALL_THICKNESS = {Material.PLA: 2.0, Material.PETG: 3.0}


class RockerSwitchMount(SidePanelMount):
    CHANNEL_LENGTH = 15.0
    CHANNEL_HEIGHT = 30.0

    CLAMP_POINTS = ()

    STEP_SPANS = ()

    def __init__(
        self,
        at: tuple[float, float, float],
        facing: SidePanelFacing,
        panel_thickness: float,
        sidewall_thickness: float,
        material: Material = Material.PLA,
    ) -> None:
        self.CHANNEL_WIDTH = CUTOUT_WIDTH[material]
        self.SAMPLE_CEILING = SAMPLE_CEILING[material]
        super().__init__(at, facing, panel_thickness, sidewall_thickness)
        self.material = material

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
    return RockerSwitchMount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_POS,
        panel_thickness=3.0,
        sidewall_thickness=SIDEWALL_THICKNESS[material],
        material=material,
    ).sample()
