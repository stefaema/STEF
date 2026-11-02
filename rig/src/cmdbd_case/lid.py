from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos
from extras.logo import LogoEngraving
from fasteners.screw import ScrewHole
from mounts.red_button_cutout import RedButtonCutout

from cmdbd_case import layout
from cmdbd_case.layout import (
    CLAMP_PILLAR_DIAMETER,
    CLAMP_SQUEEZE,
    CUT_OVERSHOOT,
    LID_SCREW,
    LID_THICKNESS,
    LOGO_DEPTH,
    LOGO_WIDTH,
)
from rig.materials import Material


def _clamp_pillars(material: Material) -> Part:
    """Pillars hanging under the lid that press the board onto its supports."""
    length = layout.wall_top(material) - layout.board_top(material) + CLAMP_SQUEEZE
    pillars = Part()
    for x, y in layout.clamp_pillar_points():
        pillars += Pos(x, y, -length) * Cylinder(
            CLAMP_PILLAR_DIAMETER / 2,
            length,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
    return pillars


def _lid(material: Material) -> Part:
    """A plate screwed into the shoebox's corner posts, pressing the board down, the logo sunk in its top.

    Its underside is z = 0, which seats on the shoebox's wall top.
    """
    plate = Part()
    for x0, x1, y0, y1 in layout.plan_rectangles():
        plate += Pos(x0, y0, 0.0) * Box(
            x1 - x0, y1 - y0, LID_THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN)
        )
    solid = plate + _clamp_pillars(material)

    screw = ScrewHole(spec=LID_SCREW, sink_head=True)
    for x, y in layout.post_points():
        solid -= Pos(x, y, LID_THICKNESS) * screw.cutter(LID_THICKNESS + CUT_OVERSHOOT)

    logo_x, logo_y = layout.logo_point()
    logo = LogoEngraving(
        at=(logo_x, logo_y, LID_THICKNESS), width=LOGO_WIDTH, depth=LOGO_DEPTH
    )
    solid -= logo.cutout()
    return cast(Part, solid)


def build(material: Material = Material.PLA) -> dict[str, Part]:
    """The lid, plain and with the button's hole near the jack wall's y = 0 corner."""
    plain = _lid(material)
    x, y = layout.button_point()
    button = RedButtonCutout(at=(x, y, 0.0), thickness=LID_THICKNESS)
    return {"plain": plain, "button": cast(Part, plain - button.cutout())}
