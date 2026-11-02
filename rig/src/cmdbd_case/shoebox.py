from typing import cast

from board_case.shoebox import CUT_OVERSHOOT, FLOOR_THICKNESS, WALL_THICKNESS, slab
from build123d import Align, Cylinder, Part, Pos

from cmdbd_case import layout
from cmdbd_case.layout import (
    GUIDE_CLEARANCE,
    GUIDE_CONTACT_LENGTH,
    INTERIOR_LENGTH,
    INTERIOR_WIDTH,
    SUPPORT_PILLAR_DIAMETER,
)
from rig.materials import Material


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
            guide += slab(x0, x1, y0, y1, FLOOR_THICKNESS, top)
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


def _board_window(material: Material) -> Part:
    y0, y1, z0, z1 = layout.board_window(material)
    return slab(
        INTERIOR_LENGTH - CUT_OVERSHOOT,
        INTERIOR_LENGTH + WALL_THICKNESS + CUT_OVERSHOOT,
        y0,
        y1,
        z0,
        z1,
    )


def build(material: Material = Material.PLA) -> Part:
    """The command board's shoebox. The connectors stand on the floor, the board sits on pillars above them, and it is open on top."""
    return layout.box().body(
        top=layout.wall_top(material),
        mounts=layout.connector_mounts(material),
        holders=cast(Part, _support_pillars(material) + _corner_guides(material)),
        openings=_board_window(material),
        material=material,
    )
