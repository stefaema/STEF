from typing import cast

from board_case.shoebox import CLAMP_SQUEEZE, hanging_pillars
from build123d import Part

from drvbd_case import layout
from drvbd_case.layout import BOARD_PILLAR_DIAMETER
from rig.materials import Material


def build(material: Material = Material.PLA) -> Part:
    """The shared lid, with pillars that land near the board's corners and hold it on the ledge."""
    length = layout.wall_top(material) - layout.board_top(material) + CLAMP_SQUEEZE
    pillars = hanging_pillars(
        layout.board_pillar_points(), BOARD_PILLAR_DIAMETER, length
    )
    return cast(Part, layout.box().lid(pillars))
