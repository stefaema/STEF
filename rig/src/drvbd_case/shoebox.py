from typing import cast

from board_case.shoebox import CUT_OVERSHOOT, WALL_THICKNESS, slab
from build123d import Cylinder, Part, Pos, Rot

from drvbd_case import layout
from drvbd_case.layout import (
    LEDGE_THICKNESS,
    LEDGE_WIDTH,
    MOTOR_HOLE_DIAMETER,
    MOTOR_HOLE_HEIGHT,
)
from rig.materials import Material


def _ledges(material: Material) -> Part:
    """The strips along both long walls that the board's edges rest on.

    They run along the long walls only, so the ends of the board zone stay
    open for the connectors' wires to climb to the board.
    """
    length = layout.interior_length()
    width = layout.interior_width()
    top = layout.ledge_top(material)
    bottom = top - LEDGE_THICKNESS
    return cast(
        Part,
        slab(0.0, length, 0.0, LEDGE_WIDTH, bottom, top)
        + slab(0.0, length, width - LEDGE_WIDTH, width, bottom, top),
    )


def _stops(material: Material) -> Part:
    """Upright ribs on both long walls, either side of the board, that keep it from sliding along x.

    They stand as far off the walls as the ledge, from its underside to the
    wall top, so they also guide the board down onto it.
    """
    width = layout.interior_width()
    bottom = layout.ledge_top(material) - LEDGE_THICKNESS
    top = layout.wall_top(material)
    stops = Part()
    for x0, x1 in layout.stop_spans():
        stops += slab(x0, x1, 0.0, LEDGE_WIDTH, bottom, top)
        stops += slab(x0, x1, width - LEDGE_WIDTH, width, bottom, top)
    return stops


def _motor_hole(material: Material) -> Part:
    """The motor cable's way out, through the wall opposite the connectors, centred across it."""
    return cast(
        Part,
        Pos(
            layout.interior_length() + WALL_THICKNESS / 2,
            layout.interior_width() / 2,
            layout.board_top(material) + MOTOR_HOLE_HEIGHT,
        )
        * Rot(0.0, 90.0, 0.0)
        * Cylinder(MOTOR_HOLE_DIAMETER / 2, WALL_THICKNESS + 2 * CUT_OVERSHOOT),
    )


def build(material: Material = Material.PLA) -> Part:
    """The driver board's shoebox. The connectors stand on the floor, the board sits on a ledge above them, and it is open on top."""
    return layout.box().body(
        top=layout.wall_top(material),
        mounts=layout.connector_mounts(material),
        holders=cast(Part, _ledges(material) + _stops(material)),
        openings=_motor_hole(material),
        material=material,
    )
