from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos
from fasteners.screw import ScrewHole

from drvbd_case import layout
from drvbd_case.layout import (
    BOARD_PILLAR_DIAMETER,
    CLAMP_SQUEEZE,
    CUT_OVERSHOOT,
    LID_SCREW,
    LID_THICKNESS,
)
from rig.materials import Material


def _board_pillars(material: Material) -> Part:
    """Posts hanging under the lid that land near the board's corners and hold it on the ledge."""
    length = layout.wall_top(material) - layout.board_top(material) + CLAMP_SQUEEZE
    pillars = Part()
    for x, y in layout.board_pillar_points():
        pillars += Pos(x, y, -length) * Cylinder(
            BOARD_PILLAR_DIAMETER / 2,
            length,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
    return pillars


def build(material: Material = Material.PLA) -> Part:
    """The lid: a plate screwed into the shoebox's corner posts, pressing the board down.

    Its underside is z = 0, which seats on the shoebox's wall top.
    """
    plate = Part()
    for x0, x1, y0, y1 in layout.plan_rectangles():
        plate += Pos(x0, y0, 0.0) * Box(
            x1 - x0, y1 - y0, LID_THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN)
        )
    solid = plate + _board_pillars(material)

    screw = ScrewHole(spec=LID_SCREW, sink_head=True)
    for x, y in layout.post_points():
        solid -= Pos(x, y, LID_THICKNESS) * screw.cutter(LID_THICKNESS + CUT_OVERSHOOT)
    return cast(Part, solid)
