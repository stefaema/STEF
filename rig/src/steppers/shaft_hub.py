from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos, Rot
from cores.axial import AxialCore
from fasteners.heat_insert import HeatInsert
from fasteners.insert_specs import INSERT_M3_SHORT, HeatInsertSpec

from rig.materials import Material
from steppers.stepper_specs import NEMA_17, NemaStepperSpec

# Added to the shaft's diameter and to its flat's distance from the axis.
BORE_CLEARANCE = {Material.PLA: 0.2, Material.PETG: 0.2}

STANDOFF = 5.0  # mounting face to the hub's end face
END_DEPTH = 7.2  # the bearing seat's depth, so motion and idler rollers share a profile
WALL_UNDER_INSERT = 2.0  # between the bore's flat and the insert pocket's floor
TUNNEL_WIDTH = 8.0  # across the tunnel, room for the iron's tip
TUNNEL_ROOF_CLEARANCE = 0.2  # between the insert's mouth and the tunnel's roof
TUNNEL_REACH = 100.0  # tunnel run past the insert's mouth, beyond any rim
HEADROOM_LENGTH = 4.0  # along the tunnel from the insert's mouth, roofed at END_DEPTH
TIP_RELIEF = 0.5  # bore carried on past the shaft's tip

CUT_OVERSHOOT = 0.5

SAMPLE_WALL = 2.0


def _aimed_at_axis(distance: float, z: float, tool: Part) -> Part:
    """Rotate `tool` so its -Z points at the axis, then move it `distance` along +X and up to `z`."""
    return cast(Part, Pos(distance, 0.0, z) * Rot(0.0, 90.0, 0.0) * tool)


class ShaftHub(AxialCore):
    """A D-bore that takes a stepper's shaft, gripped by a set screw in a radial heat insert."""

    def __init__(
        self,
        length: float,
        standoff: float = STANDOFF,
        stepper: NemaStepperSpec = NEMA_17,
        insert: HeatInsertSpec = INSERT_M3_SHORT,
        material: Material = Material.PLA,
        at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        clearance = BORE_CLEARANCE[material]
        shaft_radius = stepper.shaft_diameter / 2
        self.length = length
        self.at = at
        self.bore_radius = shaft_radius + clearance / 2
        self.bore_flat_distance = (
            shaft_radius - stepper.shaft_flat_depth + clearance / 2
        )
        self.shaft_engagement = stepper.shaft_length - standoff
        self.insert = HeatInsert(spec=insert, material=material)
        self.insert_mouth_distance = (
            self.bore_flat_distance + WALL_UNDER_INSERT + self.insert.pocket_depth
        )
        self.insert_axis_z = END_DEPTH / 2
        self.tunnel_roof_z = (
            self.insert_axis_z + self.insert.mouth_radius + TUNNEL_ROOF_CLEARANCE
        )

        if self.tunnel_roof_z >= END_DEPTH:
            raise ValueError(
                f"tunnel roof at {self.tunnel_roof_z} breaks through END_DEPTH "
                f"{END_DEPTH}"
            )
        screw_far_edge = self.insert_axis_z + self.insert.bore_radius
        if self.shaft_engagement < screw_far_edge:
            raise ValueError(
                f"shaft engagement {self.shaft_engagement} stops short of the "
                f"set screw's far edge at {screw_far_edge}"
            )
        if self.shaft_engagement > length:
            raise ValueError(
                f"shaft engagement {self.shaft_engagement} is longer than the "
                f"hub's length {length}"
            )

    @property
    def end_depth(self) -> float:
        """Depth of the end section that holds the insert and its tunnel."""
        return END_DEPTH

    def check_radius(self, radius: float) -> None:
        """Raise if `radius` doesn't reach past the insert's mouth."""
        if radius <= self.insert_mouth_distance:
            raise ValueError(
                f"radius {radius} doesn't reach past the insert's mouth at "
                f"{self.insert_mouth_distance}"
            )

    def _d_bore(self) -> Part:
        """The shaft's bore, flat on +X where the set screw lands."""
        depth = CUT_OVERSHOOT + self.shaft_engagement + TIP_RELIEF
        round_bore = Pos(0.0, 0.0, -CUT_OVERSHOOT) * Cylinder(
            self.bore_radius, depth, align=(Align.CENTER, Align.CENTER, Align.MIN)
        )
        past_flat = Pos(self.bore_flat_distance, 0.0, -CUT_OVERSHOOT) * Box(
            self.bore_radius,
            2 * self.bore_radius,
            depth,
            align=(Align.MIN, Align.CENTER, Align.MIN),
        )
        return cast(Part, round_bore - past_flat)

    def _insert_pocket(self) -> Part:
        """The insert's pocket, bored on through to the flat for the set screw."""
        floor_distance = self.insert_mouth_distance - self.insert.pocket_depth
        return _aimed_at_axis(
            self.insert_mouth_distance,
            self.insert_axis_z,
            self.insert.cutter(bore_depth=floor_distance),
        )

    def _tunnel(self) -> Part:
        """Ensures the heat insert and its set screw can be inserted easily.

        Near the insert's mouth the opening grows taller.
        """
        start = Pos(self.insert_mouth_distance, 0.0, -CUT_OVERSHOOT)
        run = start * Box(
            TUNNEL_REACH,
            TUNNEL_WIDTH,
            CUT_OVERSHOOT + self.tunnel_roof_z,
            align=(Align.MIN, Align.CENTER, Align.MIN),
        )
        headroom = start * Box(
            HEADROOM_LENGTH,
            TUNNEL_WIDTH,
            CUT_OVERSHOOT + END_DEPTH,
            align=(Align.MIN, Align.CENTER, Align.MIN),
        )
        return cast(Part, run + headroom)

    def cutters(self) -> Part:
        """Cutter for the bore, the insert pocket and the tunnel. Subtract it from the roller's body."""
        return cast(
            Part,
            Pos(*self.at) * (self._d_bore() + self._insert_pocket() + self._tunnel()),
        )


def sample(material: Material = Material.PLA) -> Part:
    """A cylinder around the bore joined to one around the insert's line, to test the shaft, insert and screw together."""
    hub = ShaftHub(length=NEMA_17.shaft_length, material=material)
    shaft_cylinder = Cylinder(
        hub.bore_radius + SAMPLE_WALL,
        hub.shaft_engagement,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    insert_cylinder = _aimed_at_axis(
        hub.insert_mouth_distance,
        hub.insert_axis_z,
        Cylinder(
            hub.insert.mouth_radius + SAMPLE_WALL,
            hub.insert_mouth_distance,
            align=(Align.CENTER, Align.CENTER, Align.MAX),
        ),
    )
    above_end_face = Box(
        4 * hub.insert_mouth_distance,
        4 * hub.insert_mouth_distance,
        hub.shaft_engagement,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    return cast(
        Part,
        (shaft_cylinder + (insert_cylinder & above_end_face)) - hub.cutters(),
    )
