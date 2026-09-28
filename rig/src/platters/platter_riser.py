import math
from typing import cast

from bearings.seat import BearingSeat
from build123d import Align, Cylinder, Part, PolarLocations, Pos
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK

from platters.platter_cap import FORMATS, bolt_circle_radius
from platters.platter_specs import PLATTER_360, PlatterSpec
from rig.materials import Material
from shared.film_formats import FILM_35MM_SILENT, FilmGeometricFormat

DATUM_FORMAT = FILM_35MM_SILENT
RISER_SCREW = SCREW_M3_COUNTERSUNK
FLOOR_UNDER_POCKET = 1.5
CUT_OVERSHOOT = 0.5


def riser_height(film_format: FilmGeometricFormat) -> float:
    """How far this gauge's film has to be lifted to reach the roller's midplane.

    The compound roller centres every gauge on one midplane, so it pins the
    film's centreline. The platter pins the film's lower edge. The gap between
    those two references is half the film's width, and only the difference from
    the datum gauge has to be made up.
    """
    return (DATUM_FORMAT.width - film_format.width) / 2


class PlatterRiser:
    """A spacer that lifts the platter without either neighbour knowing it is there.

    Its underside answers the hub's inserts with clearance holes, and its top
    face carries inserts of its own at the same two bolt circles, so the platter
    and the cap bolt down exactly as they would to the hub. Each circle's holes
    and pockets are staggered half a division apart, which is the only way three
    of each fit on one radius.
    """

    def __init__(
        self,
        height: float,
        platter: PlatterSpec = PLATTER_360,
        material: Material = Material.PLA,
    ) -> None:
        insert = HeatInsert(material=material)
        screw = ScrewHole(spec=RISER_SCREW)
        floor = height - insert.pocket_depth
        if floor < FLOOR_UNDER_POCKET:
            raise ValueError(
                f"height {height} leaves {floor} under a {insert.pocket_depth}-deep "
                f"pocket, below FLOOR_UNDER_POCKET {FLOOR_UNDER_POCKET}"
            )
        self.height = height
        self.platter = platter
        self.material = material
        self.inner_radius = BearingSeat(material=material).well_radius
        self.outer_radius = platter.bolt_circle_radius + insert.boss_radius
        self.bolt_circles = (bolt_circle_radius(material), platter.bolt_circle_radius)
        self.stagger = 180.0 / platter.bolt_count

        reach = screw.head_radius + insert.boss_radius
        for radius in self.bolt_circles:
            gap = 2 * radius * math.sin(math.radians(self.stagger) / 2)
            if gap < reach:
                raise ValueError(
                    f"bolt circle {radius} puts a screw head and an insert boss "
                    f"{gap} apart, closer than the {reach} they need"
                )

    def body(self) -> Part:
        ring = Cylinder(
            self.outer_radius,
            self.height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        bore = Pos(0.0, 0.0, -CUT_OVERSHOOT) * Cylinder(
            self.inner_radius,
            self.height + 2 * CUT_OVERSHOOT,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        return cast(Part, ring - bore)

    def screw_cutters(self) -> Part:
        """The clearance holes down onto the hub's inserts, heads sunk flush."""
        hole = ScrewHole(
            at=(0.0, 0.0, self.height), spec=RISER_SCREW, sink_head=True
        ).cutter(self.height + CUT_OVERSHOOT)
        cutters = Part()
        for radius in self.bolt_circles:
            for placed in PolarLocations(radius, self.platter.bolt_count) * hole:
                cutters += placed
        return cutters

    def insert_cutters(self) -> Part:
        """The pockets the platter's and the cap's own screws thread into."""
        pocket = HeatInsert(
            at=(0.0, 0.0, self.height),
            facing=InsertFacing.DOWN,
            material=self.material,
        ).cutter()
        cutters = Part()
        for radius in self.bolt_circles:
            placed = (
                PolarLocations(
                    radius, self.platter.bolt_count, start_angle=self.stagger
                )
                * pocket
            )
            for one in placed:
                cutters += one
        return cutters

    def screw_length(self, engagement: float) -> float:
        """Shortest screw under the head that crosses the riser and bites this deep."""
        return self.height + engagement

    def build(self) -> Part:
        return cast(Part, self.body() - self.screw_cutters() - self.insert_cutters())


def build(material: Material = Material.PLA) -> dict[str, Part]:
    """One riser per gauge that needs lifting; the datum gauge needs none."""
    return {
        name: PlatterRiser(height=riser_height(film_format), material=material).build()
        for name, film_format in FORMATS.items()
        if riser_height(film_format) > 0.0
    }
