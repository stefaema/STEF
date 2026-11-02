from typing import cast

from board_case.shoebox import CLAMP_SQUEEZE, LID_THICKNESS, hanging_pillars
from build123d import Part
from extras.logo import LogoEngraving
from mounts.red_button_cutout import RedButtonCutout

from cmdbd_case import layout
from cmdbd_case.layout import CLAMP_PILLAR_DIAMETER, LOGO_DEPTH, LOGO_WIDTH
from rig.materials import Material


def _lid(material: Material) -> Part:
    """The shared lid, with clamp pillars that press the board down and the logo sunk in its top."""
    length = layout.wall_top(material) - layout.board_top(material) + CLAMP_SQUEEZE
    pillars = hanging_pillars(
        layout.clamp_pillar_points(), CLAMP_PILLAR_DIAMETER, length
    )
    logo_x, logo_y = layout.logo_point()
    logo = LogoEngraving(
        at=(logo_x, logo_y, LID_THICKNESS), width=LOGO_WIDTH, depth=LOGO_DEPTH
    )
    return cast(Part, layout.box().lid(pillars) - logo.cutout())


def build(material: Material = Material.PLA) -> dict[str, Part]:
    """The lid, plain and with the button's hole near the jack wall's y = 0 corner."""
    plain = _lid(material)
    x, y = layout.button_point()
    button = RedButtonCutout(at=(x, y, 0.0), thickness=LID_THICKNESS)
    return {"plain": plain, "button": cast(Part, plain - button.cutout())}
