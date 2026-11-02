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

from fasteners.heat_insert import HeatInsert
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK, SCREW_M5_COUNTERSUNK
from mounts.dc_barrel_jack import DCBarrelJackMount
from mounts.red_button_cutout import BUTTON_DIAMETER
from mounts.rj45_keystone import RJ45KeystoneMount
from mounts.side_panel import SidePanelFacing, SidePanelMount

from rig.materials import Material

INTERIOR_LENGTH = 120.0  # along x, RJ45 wall to jack wall
INTERIOR_WIDTH = 120.0  # along y

BOARD_SIDE = 100.0
BOARD_THICKNESS = 1.5
BOARD_UNDERSIDE_CLEARANCE = 3.0  # above the tallest channel, for the board's leads

WALL_THICKNESS = 3.0  # the panel the RJ45 and jack samples were fitted against
FLOOR_THICKNESS = 3.0
UPPER_HEIGHT = 30.0  # board's top face to the lid

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
CLAMP_SQUEEZE = 0.2

BOARD_WINDOW_SIDE = 25.0  # square, through the jack wall from the board's underside

LID_THICKNESS = 3.0
BUTTON_WALL_DISTANCE = (
    20.0  # jack wall's and y = 0 wall's inner faces to the button's centre
)
LOGO_WALL_DISTANCE = (
    20.0  # jack wall's and y = INTERIOR_WIDTH wall's inner faces to the logo's centre
)
LOGO_WIDTH = 35.0  # along x
LOGO_DEPTH = 1.0  # into the lid's top face
BUTTON_PILLAR_CLEARANCE = 2.0  # button hole's edge to a clamp pillar's
LID_SCREW = SCREW_M3_COUNTERSUNK
LID_INSERT = INSERT_M3_SHORT
LID_SCREW_LENGTH = 8.0  # under the head

TAB_SCREW = SCREW_M5_COUNTERSUNK
TAB_THICKNESS = 5.0
TAB_WIDTH = 20.0  # along x
TAB_REACH = 16.0  # out from the wall's outer face

CUT_OVERSHOOT = 0.5


def outer_extent() -> tuple[float, float, float, float]:
    """The shoebox's rectangle in plan, as `(x0, x1, y0, y1)`, which the lid shares."""
    return (
        -WALL_THICKNESS,
        INTERIOR_LENGTH + WALL_THICKNESS,
        -WALL_THICKNESS,
        INTERIOR_WIDTH + WALL_THICKNESS,
    )


def post_half_side() -> float:
    """Half a lid post's side: the insert's boss radius, so the pocket has its wall all round."""
    return HeatInsert(spec=LID_INSERT).boss_radius


def post_points() -> tuple[tuple[float, float], ...]:
    """The four lid posts' centres, as `(x, y)`.

    Each post carries a side wall on past an end wall's outer face, its outer
    face flush with that side wall's, so the posts stand out along x only and
    the outline in plan reads as an H.
    """
    half = post_half_side()
    x0 = -WALL_THICKNESS - half
    x1 = INTERIOR_LENGTH + WALL_THICKNESS + half
    y0, y1 = -WALL_THICKNESS + half, INTERIOR_WIDTH + WALL_THICKNESS - half
    return ((x0, y0), (x1, y0), (x0, y1), (x1, y1))


def plan_rectangles() -> list[tuple[float, float, float, float]]:
    """The shoebox's outline in plan, as `(x0, x1, y0, y1)` rectangles: the walls' and each post's."""
    half = post_half_side()
    return [outer_extent()] + [
        (x - half, x + half, y - half, y + half) for x, y in post_points()
    ]


def _cutout_centre(mount: SidePanelMount) -> float:
    """Height of a mount's cutout centre above its own channel floor."""
    box = mount.cutout().bounding_box()
    return (box.min.Z + box.max.Z) / 2


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
    rj45_centre = _cutout_centre(_rj45_prototype(material))
    floor = FLOOR_THICKNESS + rj45_centre - _cutout_centre(probe)
    if floor < FLOOR_THICKNESS:
        raise ValueError(
            f"the jack's cutout centre sits above the RJ45s', so lining them "
            f"up would sink the jack {FLOOR_THICKNESS - floor} into the floor"
        )
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
    """Top of the support pillars: clear of the tallest channel or cutout by the leads' room."""
    tallest = FLOOR_THICKNESS
    for mount in connector_mounts(material):
        tallest = max(
            tallest,
            mount.body().bounding_box().max.Z,
            mount.cutout().bounding_box().max.Z,
        )
    return tallest + BOARD_UNDERSIDE_CLEARANCE


def board_top(material: Material = Material.PLA) -> float:
    return board_underside(material) + BOARD_THICKNESS


def wall_top(material: Material = Material.PLA) -> float:
    """Top of the walls and posts, which is where the lid's underside lands."""
    return board_top(material) + UPPER_HEIGHT


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
