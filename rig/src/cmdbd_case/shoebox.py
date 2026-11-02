from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.screw import ScrewHole

from cmdbd_case import layout
from cmdbd_case.layout import (
    CUT_OVERSHOOT,
    FLOOR_THICKNESS,
    GUIDE_CLEARANCE,
    GUIDE_CONTACT_LENGTH,
    INTERIOR_LENGTH,
    INTERIOR_WIDTH,
    LID_INSERT,
    LID_SCREW_LENGTH,
    LID_THICKNESS,
    SUPPORT_PILLAR_DIAMETER,
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
        0.0, INTERIOR_LENGTH, 0.0, INTERIOR_WIDTH, FLOOR_THICKNESS, top + CUT_OVERSHOOT
    )
    return cast(Part, outer - hollow)


def _support_pillars(material: Material) -> Part:
    """Round pillars from the floor up to the board's underside."""
    height = layout.board_underside(material) - FLOOR_THICKNESS
    pillars = Part()
    for x, y in layout.support_pillar_points():
        pillars += Pos(x, y, FLOOR_THICKNESS) * Cylinder(
            SUPPORT_PILLAR_DIAMETER / 2,
            height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
    return pillars


def _corner_guide(
    corner: tuple[float, float],
    wall: tuple[float, float],
    inward: tuple[float, float],
    top: float,
) -> Part:
    """One L, filled from its two inner faces out to the walls at `wall`.

    An arm whose face is the wall itself has no thickness and is left out.
    """
    (corner_x, corner_y), (wall_x, wall_y), (inward_x, inward_y) = corner, wall, inward
    face_x = corner_x - inward_x * GUIDE_CLEARANCE
    face_y = corner_y - inward_y * GUIDE_CLEARANCE
    arm_end_x = corner_x + inward_x * GUIDE_CONTACT_LENGTH
    arm_end_y = corner_y + inward_y * GUIDE_CONTACT_LENGTH

    guide = Part()
    for xs, ys in (
        ((wall_x, face_x), (wall_y, arm_end_y)),
        ((wall_x, arm_end_x), (wall_y, face_y)),
    ):
        x0, x1 = sorted(xs)
        y0, y1 = sorted(ys)
        if x1 > x0 and y1 > y0:
            guide += _slab(x0, x1, y0, y1, FLOOR_THICKNESS, top)
    return guide


def _corner_guides(material: Material) -> Part:
    """An L at each of the board's corners, floor to wall top, that keeps it from sliding.

    Its two inner faces stand `GUIDE_CLEARANCE` off the board's edges and run
    `GUIDE_CONTACT_LENGTH` along each from the corner.
    """
    bx0, bx1, by0, by1 = layout.board_extent()
    top = layout.wall_top(material)
    guides = Part()
    for corner_x, wall_x, inward_x in ((bx0, 0.0, 1.0), (bx1, INTERIOR_LENGTH, -1.0)):
        for corner_y, wall_y, inward_y in (
            (by0, 0.0, 1.0),
            (by1, INTERIOR_WIDTH, -1.0),
        ):
            guides += _corner_guide(
                (corner_x, corner_y), (wall_x, wall_y), (inward_x, inward_y), top
            )
    return guides


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


def _board_window(material: Material) -> Part:
    y0, y1, z0, z1 = layout.board_window(material)
    return _slab(
        INTERIOR_LENGTH - CUT_OVERSHOOT,
        INTERIOR_LENGTH + WALL_THICKNESS + CUT_OVERSHOOT,
        y0,
        y1,
        z0,
        z1,
    )


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


def _tab_centres() -> tuple[tuple[float, float], ...]:
    """The table screws, one in each tab, as `(x, y)`."""
    _, _, y0, y1 = layout.outer_extent()
    x = INTERIOR_LENGTH / 2
    return ((x, y0 - TAB_REACH / 2), (x, y1 + TAB_REACH / 2))


def _tabs() -> Part:
    """Two flanges standing out of the side walls at the ground."""
    _, _, y0, y1 = layout.outer_extent()
    x = INTERIOR_LENGTH / 2
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
    """The command board's shoebox: connectors on the floor, the board on pillars above them, open on top."""
    bodies, cutouts = Part(), Part()
    for mount in layout.connector_mounts(material):
        bodies += mount.body()
        cutouts += mount.cutout()

    solid = _shell(material) + _posts(material) + _tabs()
    solid += _support_pillars(material) + _corner_guides(material)
    solid += _plinths(material) + bodies
    solid -= cutouts
    solid -= _board_window(material)
    solid -= _post_inserts(material)
    solid -= _tab_holes()
    return cast(Part, solid)
