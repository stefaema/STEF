# Attempt to refactor, too large and convoluted (whole platter module, not only hub).

from typing import cast

from bearings.core import BearingCore, BearingPlacement
from bearings.seat import BearingSeat
from build123d import Part, PolarLocations, Pos, Rot
from fasteners.heat_insert import HeatInsert, InsertFacing
from pulleys.pulley import DRIVE_PULLEY, TimingPulley

from platters.platter_cap import bolt_circle_radius
from platters.platter_seat import CONE_WALL_ANGLE, PlatterSeat
from platters.platter_specs import PLATTER_360, PlatterSpec
from rig.materials import Material

TOP_BEARING_RECESS = 18.0
CUT_OVERSHOOT = 0.5


class PlatterHub:
    """Turns a platter from below, riding on a fixed rod.

    Bottom to top: the pulley the belt drives, the cone that carries the
    platter, and a bearing at each end. The rod does not turn, so it is the
    bearings' outer races that go round with this part.

    The lower bearing takes the weight. Its pocket opens downward, so the
    shoulder above it presses on the outer race and the load passes out to
    whatever holds the rod. The upper bearing is just to keep the platter from wobbling and heighting the cone.
    """

    def __init__(
        self,
        pulley: TimingPulley = DRIVE_PULLEY,
        platter: PlatterSpec = PLATTER_360,
        material: Material = Material.PLA,
        wall_angle: float = CONE_WALL_ANGLE,
    ) -> None:
        self.pulley = pulley
        self.platter = platter
        self.material = material

        self.bearing_seat = BearingSeat(material=material)
        self.bearing_seat.check_radius(pulley.band.root_radius)

        self.seat = PlatterSeat(
            base_radius=pulley.flange.diameter(pulley.band) / 2,
            platter=platter,
            material=material,
            base_height=pulley.height,
            wall_angle=wall_angle,
        )
        self.height = self.seat.top_height
        self.core = BearingCore(
            length=self.height - TOP_BEARING_RECESS,
            seat=self.bearing_seat,
            bearing_at=BearingPlacement.BOTH_SIDES,
        )

    def body(self) -> Part:
        """Pulley, cone and the solid around the bore, before anything is cut."""
        return cast(Part, self.pulley.build() + self.seat.body() + self.core.body())

    def cap_insert_cutters(self) -> list[Part]:
        """The pockets the cap's screws thread into, on the inner of the two bolt circles."""
        pocket = HeatInsert(
            at=(0.0, 0.0, self.seat.top_height),
            facing=InsertFacing.DOWN,
            material=self.material,
        ).cutter()
        return (
            PolarLocations(bolt_circle_radius(self.material), self.platter.bolt_count)
            * pocket
        )

    def well_cutter(self) -> Part:
        return cast(
            Part,
            Pos(0.0, 0.0, self.core.length)
            * self.bearing_seat.well(TOP_BEARING_RECESS + CUT_OVERSHOOT),
        )

    def build(self) -> Part:
        solid = self.body() - self.core.cutters()
        solid -= self.well_cutter()
        solid -= self.seat.insert_cutters()
        solid -= self.cap_insert_cutters()
        return cast(Part, solid)


def build(material: Material = Material.PLA) -> Part:
    """The hub turned over, which is how it prints.

    On the bed the seat face is the flattest surface the printer makes, its six
    pockets open as first-layer holes, and the cone narrows going up rather than
    overhanging, so no angle of cone needs support.
    """
    hub = PlatterHub(material=material)
    return cast(Part, Pos(0.0, 0.0, hub.height) * Rot(180.0, 0.0, 0.0) * hub.build())
