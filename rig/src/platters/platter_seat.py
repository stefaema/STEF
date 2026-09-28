import math
from typing import cast

from build123d import (
    Align,
    Cone,
    Cylinder,
    Part,
    PolarLocations,
    Pos,
)
from fasteners.heat_insert import HeatInsert, InsertFacing

from platters.platter_specs import PLATTER_360, PlatterSpec
from rig.materials import Material

# Measured from vertical. Steeper is a shorter cone, which lowers the platter
# but brings the two bearings closer together, and their spacing is what keeps
# the belt from rocking the hub.
CONE_WALL_ANGLE = 45.0

# Flat top the platter lands on. Deep enough for an insert pocket and a floor
# under it, which the cone alone does not give at the bolt circle.
TOP_PLATE_THICKNESS = 6.0

CUT_OVERSHOOT = 0.5


class PlatterSeat:
    """The cone the platter bolts down onto, widening from the pulley to a flat top face.

    Its top face is where the platter's underside sits, and it carries the
    pockets the platter's own screws thread into.
    """

    def __init__(
        self,
        base_radius: float,
        platter: PlatterSpec = PLATTER_360,
        material: Material = Material.PLA,
        base_height: float = 0.0,
        wall_angle: float = CONE_WALL_ANGLE,
    ) -> None:
        self.platter = platter
        self.material = material
        self.base_radius = base_radius
        self.base_height = base_height
        self.wall_angle = wall_angle
        if not 0.0 < wall_angle < 90.0:
            raise ValueError(
                f"wall angle {wall_angle} is not between vertical and flat"
            )
        self.rim_radius = (
            platter.bolt_circle_radius + HeatInsert(material=material).boss_radius
        )
        if self.rim_radius <= base_radius:
            raise ValueError(
                f"base radius {base_radius} already reaches the rim "
                f"{self.rim_radius}, leaving no cone to print"
            )
        self.cone_height = (self.rim_radius - base_radius) / math.tan(
            math.radians(wall_angle)
        )
        self.height = self.cone_height + TOP_PLATE_THICKNESS

    @property
    def top_height(self) -> float:
        """Height of the flat face, which is where the platter's underside lands."""
        return self.base_height + self.height

    def body(self) -> Part:
        """The cone and the flat plate on top of it, before any pocket is cut."""
        cone = Cone(
            bottom_radius=self.base_radius,
            top_radius=self.rim_radius,
            height=self.cone_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        plate = Pos(0.0, 0.0, self.cone_height) * Cylinder(
            self.rim_radius,
            TOP_PLATE_THICKNESS,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        return cast(Part, Pos(0.0, 0.0, self.base_height) * (cone + plate))

    def _underside_depth_at(self, radius: float) -> float:
        return self.height - (radius - self.base_radius) / math.tan(
            math.radians(self.wall_angle)
        )

    def insert_cutters(self) -> list[Part]:
        """The pockets the platter's screws thread into, cut down from the top face."""
        insert = HeatInsert(
            at=(0.0, 0.0, self.top_height),
            facing=InsertFacing.DOWN,
            material=self.material,
        )
        breakout = self._underside_depth_at(
            self.platter.bolt_circle_radius - insert.bore_radius
        )
        pocket = insert.cutter(breakout - insert.pocket_depth + CUT_OVERSHOOT)
        return (
            PolarLocations(self.platter.bolt_circle_radius, self.platter.bolt_count)
            * pocket
        )

    def build(self) -> Part:
        return cast(Part, self.body() - self.insert_cutters())


def sample(material: Material = Material.PLA) -> Part:
    """A flat ring carrying the three pockets, to check the bolt circle against the real platter.

    The holes in the platter are drilled and cannot move, so this proves they
    line up before the hub is printed at full height.
    """
    platter = PLATTER_360
    # The ring is exactly as wide as a pocket and its walls, so the pockets sit
    # centred in it and nothing is printed that the check does not use.
    boss_radius = HeatInsert(material=material).boss_radius

    ring = Cylinder(
        platter.bolt_circle_radius + boss_radius,
        TOP_PLATE_THICKNESS,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    ) - Pos(0.0, 0.0, -CUT_OVERSHOOT) * Cylinder(
        platter.bolt_circle_radius - boss_radius,
        TOP_PLATE_THICKNESS + 2 * CUT_OVERSHOOT,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )

    pockets = (
        PolarLocations(platter.bolt_circle_radius, platter.bolt_count)
        * HeatInsert(
            at=(0.0, 0.0, TOP_PLATE_THICKNESS),
            facing=InsertFacing.DOWN,
            material=material,
        ).cutter()
    )

    return cast(Part, ring - pockets)
