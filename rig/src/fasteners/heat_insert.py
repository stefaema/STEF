from enum import Enum
from typing import cast

from build123d import (
    Align,
    Axis,
    Box,
    Part,
    Plane,
    Polygon,
    Pos,
    Rot,
    revolve,
)

from fasteners.insert_specs import INSERT_M3_SHORT, HeatInsertSpec
from rig.materials import Material

# Added to the insert's diameters to get the pocket's.
MELT_CLEARANCE = {Material.PLA: 0.1, Material.PETG: 0.1}

BOTTOM_RELIEF = 0.2  # pocket depth past the insert's height
BORE_OVERRUN = 1.0  # bore carried on past the screw's tip
MINIMUM_WALL_THICKNESS = 2.0

CUT_OVERSHOOT = 0.5  # how far the cutter stands above the surface

SAMPLE_SLAB = (20.0, 20.0, 10.0)
SAMPLE_SCREW_LENGTH = 10.0


class InsertFacing(Enum):
    """Which way the pocket runs from the surface it is cut at."""

    DOWN = "down"
    UP = "up"


class HeatInsert:
    """Pocket geometry that takes a heat-set insert at a surface."""

    def __init__(
        self,
        at: tuple[float, float, float] = (0.0, 0.0, 0.0),
        facing: InsertFacing = InsertFacing.DOWN,
        spec: HeatInsertSpec = INSERT_M3_SHORT,
        material: Material = Material.PLA,
    ) -> None:
        clearance = MELT_CLEARANCE[material]
        self.spec = spec
        self.mouth_radius = (spec.mouth_diameter + clearance) / 2
        self.end_radius = (spec.end_diameter + clearance) / 2
        self.bore_radius = spec.clearance_hole / 2
        self.pocket_depth = spec.height + BOTTOM_RELIEF
        self._placement = Pos(*at) * Rot(
            180.0 if facing is InsertFacing.UP else 0.0, 0.0, 0.0
        )

    @property
    def boss_radius(self) -> float:
        """Minimum solid radius needed to enclose the pocket and its wall."""
        return self.mouth_radius + MINIMUM_WALL_THICKNESS

    def check_radius(self, radius: float) -> None:
        if radius < self.boss_radius:
            raise ValueError(
                f"radius {radius} is below boss_radius {self.boss_radius}, "
                f"wall would be thinner than MINIMUM_WALL_THICKNESS {MINIMUM_WALL_THICKNESS}"
            )

    def bore_depth_for(
        self, screw_length: float, overrun: float = BORE_OVERRUN
    ) -> float:
        """Bore length past the pocket floor that clears a screw this long.

        `screw_length` is measured under the head, which sits at the surface.
        """
        return max(0.0, screw_length + overrun - self.pocket_depth)

    def cutter(self, bore_depth: float = 0.0) -> Part:
        """Solid to subtract from another piece to leave an insert pocket.

        `bore_depth` is what `bore_depth_for` returns; at 0 the pocket is blind.
        """
        if bore_depth and self.bore_radius > self.end_radius:
            raise ValueError(
                f"bore radius {self.bore_radius} exceeds the pocket's narrow "
                f"end {self.end_radius}, the bore would undercut the insert"
            )

        floor = -self.pocket_depth
        profile = Polygon(
            (0.0, CUT_OVERSHOOT),
            (self.mouth_radius, CUT_OVERSHOOT),
            (self.mouth_radius, 0.0),
            (self.end_radius, floor),
            (self.bore_radius, floor),
            (self.bore_radius, floor - bore_depth),
            (0.0, floor - bore_depth),
            align=None,
        )
        pocket = revolve((Plane.XZ * profile).face(), axis=Axis.Z)
        return cast(Part, self._placement * pocket)


def sample(material: Material = Material.PLA) -> Part:
    """A slab with one pocket in its top face, bored for a 10mm screw."""
    length, width, height = SAMPLE_SLAB
    slab = Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    insert = HeatInsert(
        at=(0.0, 0.0, height), facing=InsertFacing.DOWN, material=material
    )
    return cast(Part, slab - insert.cutter(insert.bore_depth_for(SAMPLE_SCREW_LENGTH)))
