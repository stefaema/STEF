from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos, Rot
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.screw import ScrewHole

from drvbd_case import layout
from drvbd_case.layout import (
    CUT_OVERSHOOT,
    FLOOR_THICKNESS,
    LEDGE_THICKNESS,
    LEDGE_WIDTH,
    LID_INSERT,
    LID_SCREW_LENGTH,
    LID_THICKNESS,
    MOTOR_HOLE_DIAMETER,
    MOTOR_HOLE_HEIGHT,
    TAB_REACH,
    TAB_SCREW,
    TAB_THICKNESS,
    TAB_WIDTH,
    WALL_THICKNESS,
)
from rig.materials import Material


def _slab(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return cast(
        Part,
        Pos(x0, y0, z0)
        * Box(x1 - x0, y1 - y0, z1 - z0, align=(Align.MIN, Align.MIN, Align.MIN)),
    )


def _shell(material: Material) -> Part:
    """Floor and four walls, open on top."""
    x0, x1, y0, y1 = layout.outer_extent()
    top = layout.wall_top(material)
    outer = _slab(x0, x1, y0, y1, 0.0, top)
    hollow = _slab(
        0.0,
        layout.interior_length(),
        0.0,
        layout.interior_width(),
        FLOOR_THICKNESS,
        top + CUT_OVERSHOOT,
    )
    return cast(Part, outer - hollow)


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
        _slab(0.0, length, 0.0, LEDGE_WIDTH, bottom, top)
        + _slab(0.0, length, width - LEDGE_WIDTH, width, bottom, top),
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
        stops += _slab(x0, x1, 0.0, LEDGE_WIDTH, bottom, top)
        stops += _slab(x0, x1, width - LEDGE_WIDTH, width, bottom, top)
    return stops


def _plinths(material: Material) -> Part:
    """A block under each raised mount, from the floor up to its channel, which has no floor of its own."""
    plinths = Part()
    for mount in layout.connector_mounts(material):
        box = mount.body().bounding_box()
        if box.min.Z > FLOOR_THICKNESS:
            plinths += _slab(
                box.min.X, box.max.X, box.min.Y, box.max.Y, FLOOR_THICKNESS, box.min.Z
            )
    return plinths


def _posts(material: Material) -> Part:
    """A square post at each corner, ground to wall top, carrying a lid insert."""
    half = layout.post_half_side()
    top = layout.wall_top(material)
    posts = Part()
    for x, y in layout.post_points():
        posts += _slab(x - half, x + half, y - half, y + half, 0.0, top)
    return posts


def _post_inserts(material: Material) -> Part:
    insert = HeatInsert(spec=LID_INSERT, facing=InsertFacing.DOWN, material=material)
    bore = insert.bore_depth_for(LID_SCREW_LENGTH - LID_THICKNESS)
    top = layout.wall_top(material)
    cutters = Part()
    for x, y in layout.post_points():
        cutters += Pos(x, y, top) * insert.cutter(bore)
    return cutters


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


def _tab_centres() -> tuple[tuple[float, float], ...]:
    """The table screws, one in each tab, as `(x, y)`."""
    _, _, y0, y1 = layout.outer_extent()
    x = layout.interior_length() / 2
    return ((x, y0 - TAB_REACH / 2), (x, y1 + TAB_REACH / 2))


def _tabs() -> Part:
    """Two flanges standing out of the long walls at the ground."""
    _, _, y0, y1 = layout.outer_extent()
    x = layout.interior_length() / 2
    x0, x1 = x - TAB_WIDTH / 2, x + TAB_WIDTH / 2
    return cast(
        Part,
        _slab(x0, x1, y0 - TAB_REACH, y0, 0.0, TAB_THICKNESS)
        + _slab(x0, x1, y1, y1 + TAB_REACH, 0.0, TAB_THICKNESS),
    )


def _tab_holes() -> Part:
    screw = ScrewHole(spec=TAB_SCREW, sink_head=True)
    cutters = Part()
    for x, y in _tab_centres():
        cutters += Pos(x, y, TAB_THICKNESS) * screw.cutter(
            TAB_THICKNESS + CUT_OVERSHOOT
        )
    return cutters


def build(material: Material = Material.PLA) -> Part:
    """The driver board's shoebox: connectors on the floor, the board on a ledge above them, open on top."""
    bodies, cutouts = Part(), Part()
    for mount in layout.connector_mounts(material):
        bodies += mount.body()
        cutouts += mount.cutout()

    solid = _shell(material) + _ledges(material) + _posts(material) + _tabs()
    solid += _stops(material) + _plinths(material) + bodies
    solid -= cutouts
    solid -= _motor_hole(material)
    solid -= _post_inserts(material)
    solid -= _tab_holes()
    return cast(Part, solid)
