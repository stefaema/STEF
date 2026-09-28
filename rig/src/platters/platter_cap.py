from typing import cast

from bearings.seat import BearingSeat
from build123d import (
    Align,
    Axis,
    Box,
    Part,
    Plane,
    PolarLocations,
    Polygon,
    Pos,
    Rot,
    revolve,
)
from fasteners.heat_insert import HeatInsert
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK

from platters.platter_specs import PLATTER_360, PlatterSpec
from rig.materials import Material
from shared.film_formats import (
    FILM_16MM_SILENT,
    FILM_35MM_SILENT,
    FILM_SUPER8,
    FilmGeometricFormat,
)

# Bore of the film cores this stands in, one inch.
CORE_BORE_DIAMETER = 25.4

# Taken off the platter's hole diameter.
CENTRE_HOLE_FIT = {Material.PLA: 0.1, Material.PETG: 0.2}

# taken off the platter's thickness, so the brim is flush with the platter's top
BRIM_FLUSH_CLEARANCE = 0.1

# taken off the core's bore, so the core slides on
CORE_FIT = {Material.PLA: 0.1, Material.PETG: 0.1}
CROWN_LEAD_IN = 1.0  # taper at the crown's top, so a core starts on squarely

# The key on the crown, which the notch in the core's bore drops over.
CORE_KEY_WIDTH = 4.0  # across the crown
CORE_KEY_LENGTH = 3.0  # out from the crown's surface, away from the axis
# taken off the width, so the key enters the core's notch
CORE_KEY_FIT = {Material.PLA: 0.1, Material.PETG: 0.1}
CORE_KEY_ROOT_OVERLAP = 0.5  # how far the key reaches back into the crown
# Opposite one screw, and midway between the other two.
CORE_KEY_ANGLE = 180.0

# Clears the rod and the bearing's inner race. Both stand still while the cap
# turns, so the cap must not reach them.
AXLE_RELIEF_RADIUS = 7.0
AXLE_RELIEF_DEPTH = 2.0

CUT_OVERSHOOT = 0.5

FORMATS: dict[str, FilmGeometricFormat] = {
    "8mm": FILM_SUPER8,
    "16mm": FILM_16MM_SILENT,
    "35mm": FILM_35MM_SILENT,
}


def bolt_circle_radius(material: Material = Material.PLA) -> float:
    """Smallest radius the cap's screws sit on, clear of the bearing pocket's wall and their own."""
    return (
        BearingSeat(material=material).boss_radius
        + HeatInsert(material=material).boss_radius
    )


class PlatterCap:
    """Fills the platter's centre hole, and stands a crown the film core slides onto.

    It bolts to the hub.
    """

    def __init__(
        self,
        film_format: FilmGeometricFormat,
        platter: PlatterSpec = PLATTER_360,
        material: Material = Material.PLA,
    ) -> None:
        self.platter = platter
        self.film_format = film_format
        self.material = material
        self.brim_radius = (
            platter.centre_hole_diameter - CENTRE_HOLE_FIT[material]
        ) / 2
        self.brim_thickness = platter.thickness - BRIM_FLUSH_CLEARANCE
        self.crown_radius = (CORE_BORE_DIAMETER - CORE_FIT[material]) / 2
        self.bolt_circle_radius = bolt_circle_radius(material)
        # The crown stands as tall as the film is wide, so the innermost wrap
        # is supported over its whole height.
        self.height = self.brim_thickness + film_format.width

    def body(self) -> Part:
        """Brim, crown and axle relief, as one profile turned about the axis."""
        profile = Polygon(
            (0.0, AXLE_RELIEF_DEPTH),
            (AXLE_RELIEF_RADIUS, AXLE_RELIEF_DEPTH),
            (AXLE_RELIEF_RADIUS, 0.0),
            (self.brim_radius, 0.0),
            (self.brim_radius, self.brim_thickness),
            (self.crown_radius, self.brim_thickness),
            (self.crown_radius, self.height - CROWN_LEAD_IN),
            (self.crown_radius - CROWN_LEAD_IN, self.height),
            (0.0, self.height),
            align=None,
        )
        return cast(Part, revolve((Plane.XZ * profile).face(), axis=Axis.Z))

    def screw_cutters(self) -> Part:
        """The three holes down through the brim, heads sunk so the core sits flat on it."""
        hole = ScrewHole(
            at=(0.0, 0.0, self.brim_thickness),
            spec=SCREW_M3_COUNTERSUNK,
            sink_head=True,
        )
        return cast(
            Part,
            PolarLocations(self.bolt_circle_radius, self.platter.bolt_count)
            * hole.cutter(self.brim_thickness + CUT_OVERSHOOT),
        )

    def key(self) -> Part:
        """The key standing out from the crown, which the core's notch drops over.

        It stops short of the crown's lead-in, so the core starts onto the
        cylinder first and only then has a notch to line up.
        """
        tooth = Box(
            CORE_KEY_LENGTH + CORE_KEY_ROOT_OVERLAP,
            CORE_KEY_WIDTH - CORE_KEY_FIT[self.material],
            self.film_format.width - CROWN_LEAD_IN,
            align=(Align.MIN, Align.CENTER, Align.MIN),
        )
        placed = (
            Pos(self.crown_radius - CORE_KEY_ROOT_OVERLAP, 0.0, self.brim_thickness)
            * tooth
        )
        return cast(Part, Rot(0.0, 0.0, CORE_KEY_ANGLE) * placed)

    def build(self) -> Part:
        return cast(Part, (self.body() + self.key()) - self.screw_cutters())


def build(material: Material = Material.PLA) -> dict[str, Part]:
    """One cap per format, only the crown's height changes between them."""
    return {
        name: PlatterCap(film_format=film_format, material=material).build()
        for name, film_format in FORMATS.items()
    }
