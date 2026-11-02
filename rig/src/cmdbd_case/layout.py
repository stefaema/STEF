"""Where everything in the command board's case sits, shared by the shoebox and its lid.

The frame is the interior's: x runs from the RJ45 wall's inner face to the
jack wall's, y runs across them, and z = 0 is the ground the shoebox stands on.

Two stories, like the driver board's case. The RJ45s and the jack stand on the
floor and break out through opposite walls. The board rests on pillars above
them, kept in place sideways by an L at each corner, and the lid closes the
story above the board.
"""

from functools import lru_cache
from itertools import pairwise
from math import hypot

from board_case.shoebox import (
    FLOOR_THICKNESS,
    WALL_THICKNESS,
    Shoebox,
    clear_above,
    floor_level_with,
)
from board_case.shoebox import wall_top as _wall_top
from mounts.dc_barrel_jack import DCBarrelJackMount
from mounts.red_button_cutout import BUTTON_DIAMETER
from mounts.rj45_keystone import RJ45KeystoneMount
from mounts.side_panel import SidePanelFacing, SidePanelMount

from rig.materials import Material

INTERIOR_LENGTH = 120.0  # along x, RJ45 wall to jack wall
INTERIOR_WIDTH = 120.0  # along y

BOARD_SIDE = 100.0
BOARD_THICKNESS = 1.5

RJ45_COUNT = 3

GUIDE_CLEARANCE = 1.0  # board's edge to a corner guide's face
GUIDE_CONTACT_LENGTH = 2.0  # along each board edge, from the board's corner

SUPPORT_PILLAR_DIAMETER = 5.0
CLAMP_PILLAR_DIAMETER = 4.0
# From the board's corner at max x and min y, the jack's side, to each pillar's
# centre: x runs back into the board, y across it.
SUPPORT_PILLAR_OFFSETS = ((-5.0, 5.0), (-5.0, 95.0))
SUPPORT_PILLAR_EDGE_DISTANCE = (
    5.0  # board's RJ45-side edge to the pillars between the RJ45s
)
CLAMP_PILLAR_OFFSETS = ((-7.0, 27.0), (-7.0, 72.0), (-75.0, 22.0), (-75.0, 70.0))

BOARD_WINDOW_SIDE = 25.0  # square, through the jack wall from the board's underside

BUTTON_WALL_DISTANCE = (
    20.0  # jack wall's and y = 0 wall's inner faces to the button's centre
)
LOGO_WALL_DISTANCE = (
    20.0  # jack wall's and y = INTERIOR_WIDTH wall's inner faces to the logo's centre
)
LOGO_WIDTH = 35.0  # along x
LOGO_DEPTH = 1.0  # into the lid's top face
BUTTON_PILLAR_CLEARANCE = 2.0  # button hole's edge to a clamp pillar's


def box() -> Shoebox:
    return Shoebox(INTERIOR_LENGTH, INTERIOR_WIDTH)


def _rj45_prototype(material: Material) -> RJ45KeystoneMount:
    """One RJ45 at the origin, built only to be measured."""
    return RJ45KeystoneMount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_POS,
        panel_thickness=WALL_THICKNESS,
        material=material,
    )


def rj45_mounts(material: Material = Material.PLA) -> list[RJ45KeystoneMount]:
    """The RJ45s on the floor against the x = 0 wall, the slack across it split evenly into the gaps."""
    probe = _rj45_prototype(material)
    span = probe.CHANNEL_WIDTH + 2 * probe.sidewall_thickness
    gap = (INTERIOR_WIDTH - RJ45_COUNT * span) / (RJ45_COUNT + 1)
    if gap < 0.0:
        raise ValueError(
            f"{RJ45_COUNT} RJ45s need {RJ45_COUNT * span} across a wall "
            f"{INTERIOR_WIDTH} wide"
        )
    return [
        RJ45KeystoneMount(
            at=(0.0, (n + 1) * gap + (n + 0.5) * span, FLOOR_THICKNESS),
            facing=SidePanelFacing.X_POS,
            panel_thickness=WALL_THICKNESS,
            material=material,
        )
        for n in range(RJ45_COUNT)
    ]


def jack_mount(material: Material = Material.PLA) -> DCBarrelJackMount:
    """The jack against the x = INTERIOR_LENGTH wall, centred across it.

    Raised until its cutout's centre is level with the RJ45s', so the openings
    on the two walls share one height.
    """
    probe = DCBarrelJackMount(
        at=(0.0, 0.0, 0.0),
        facing=SidePanelFacing.X_NEG,
        panel_thickness=WALL_THICKNESS,
        material=material,
    )
    floor = floor_level_with(_rj45_prototype(material), probe)
    return DCBarrelJackMount(
        at=(INTERIOR_LENGTH, INTERIOR_WIDTH / 2, floor),
        facing=SidePanelFacing.X_NEG,
        panel_thickness=WALL_THICKNESS,
        material=material,
    )


def connector_mounts(material: Material = Material.PLA) -> list[SidePanelMount]:
    return [*rj45_mounts(material), jack_mount(material)]


@lru_cache(maxsize=None)
def board_underside(material: Material = Material.PLA) -> float:
    """Top of the support pillars. It clears every connector by the board leads' room."""
    return clear_above(connector_mounts(material))


def board_top(material: Material = Material.PLA) -> float:
    return board_underside(material) + BOARD_THICKNESS


def wall_top(material: Material = Material.PLA) -> float:
    return _wall_top(board_top(material))


def board_extent() -> tuple[float, float, float, float]:
    """The board in plan, as `(x0, x1, y0, y1)`: its clearance off the jack wall, centred across."""
    x0 = INTERIOR_LENGTH - GUIDE_CLEARANCE - BOARD_SIDE
    y0 = (INTERIOR_WIDTH - BOARD_SIDE) / 2
    if x0 < GUIDE_CLEARANCE or y0 < GUIDE_CLEARANCE:
        raise ValueError(
            f"a {BOARD_SIDE} board leaves no room for its {GUIDE_CLEARANCE} "
            f"guide clearance in a {INTERIOR_LENGTH} by {INTERIOR_WIDTH} interior"
        )
    return (x0, x0 + BOARD_SIDE, y0, y0 + BOARD_SIDE)


def _from_board_corner(
    offsets: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    """Pillar offsets turned into interior `(x, y)`, raising if one falls off the board."""
    x0, x1, y0, y1 = board_extent()
    points = tuple((x1 + dx, y0 + dy) for dx, dy in offsets)
    for x, y in points:
        if not (x0 < x < x1 and y0 < y < y1):
            raise ValueError(f"pillar at ({x}, {y}) falls off the board")
    return points


def support_pillar_points() -> tuple[tuple[float, float], ...]:
    """Where the board rests, as `(x, y)`: by the jack's corners, and between each pair of RJ45s."""
    x = board_extent()[0] + SUPPORT_PILLAR_EDGE_DISTANCE
    between: list[tuple[float, float]] = []
    for near, far in pairwise(rj45_mounts()):
        near_side = near.body().bounding_box().max.Y
        far_side = far.body().bounding_box().min.Y
        if far_side - near_side < SUPPORT_PILLAR_DIAMETER:
            raise ValueError(
                f"the {far_side - near_side} gap between two RJ45s is narrower "
                f"than a support pillar {SUPPORT_PILLAR_DIAMETER}"
            )
        between.append((x, (near_side + far_side) / 2))
    return _from_board_corner(SUPPORT_PILLAR_OFFSETS) + tuple(between)


def clamp_pillar_points() -> tuple[tuple[float, float], ...]:
    """Where the lid presses the board onto its supports, as `(x, y)`."""
    return _from_board_corner(CLAMP_PILLAR_OFFSETS)


def board_window(
    material: Material = Material.PLA,
) -> tuple[float, float, float, float]:
    """The opening in the jack wall, as `(y0, y1, z0, z1)`: centred across it, sill at the board's underside."""
    y = INTERIOR_WIDTH / 2
    z = board_underside(material)
    half = BOARD_WINDOW_SIDE / 2
    return (y - half, y + half, z, z + BOARD_WINDOW_SIDE)


def button_point() -> tuple[float, float]:
    """The lid's button centre, as `(x, y)`, raising if its hole would cut into a clamp pillar."""
    x = INTERIOR_LENGTH - BUTTON_WALL_DISTANCE
    y = BUTTON_WALL_DISTANCE
    reach = BUTTON_DIAMETER / 2 + BUTTON_PILLAR_CLEARANCE + CLAMP_PILLAR_DIAMETER / 2
    for px, py in clamp_pillar_points():
        if hypot(px - x, py - y) < reach:
            raise ValueError(
                f"the button at ({x}, {y}) comes within {BUTTON_PILLAR_CLEARANCE} "
                f"of the clamp pillar at ({px}, {py})"
            )
    return (x, y)


def logo_point() -> tuple[float, float]:
    """The lid's logo centre, as `(x, y)`, in the corner opposite the button across y."""
    return (INTERIOR_LENGTH - LOGO_WALL_DISTANCE, INTERIOR_WIDTH - LOGO_WALL_DISTANCE)
