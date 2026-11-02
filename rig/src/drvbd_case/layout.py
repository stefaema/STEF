"""Where everything in the driver board's case sits, shared by the shoebox and its lid.

The frame is the interior's: x runs along the board zone's long side, from
the connector wall's inner face to the motor wall's, y runs across it, and
z = 0 is the ground the shoebox stands on.

Two stories, like the PSU case. The RJ45 and the jack stand on the floor and
break out through the connector wall. The board rests on a ledge along both
long walls, above them, and the lid closes the story above the board.
"""

from functools import lru_cache

from fasteners.heat_insert import HeatInsert
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK, SCREW_M5_COUNTERSUNK
from mounts.dc_barrel_jack import DCBarrelJackMount
from mounts.rj45_keystone import RJ45KeystoneMount
from mounts.side_panel import SidePanelFacing, SidePanelMount

from rig.materials import Material

BOARD_ZONE_LENGTH = 72.0  # along x, the board with its terminal
BOARD_SIDE = 50.0
BOARD_THICKNESS = 1.6
BOARD_CLEARANCE = 0.5  # between the board's edge and a long wall
BOARD_UNDERSIDE_CLEARANCE = 3.0  # above the tallest channel, for the board's leads

WALL_THICKNESS = 3.0  # the panel the RJ45 and jack samples were fitted against
FLOOR_THICKNESS = 3.0
UPPER_HEIGHT = 30.0  # board's top face to the lid

LEDGE_WIDTH = 1.0  # out from the long walls' inner faces
LEDGE_THICKNESS = 2.0

STOP_THICKNESS = 1.0  # along x
STOP_GAP = 51.0  # clear, between the two stops' facing sides
STOP_MOTOR_WALL_DISTANCE = 5.0  # motor wall's inner face to the near stop's board side

LID_THICKNESS = 3.0
LID_SCREW = SCREW_M3_COUNTERSUNK
LID_INSERT = INSERT_M3_SHORT
LID_SCREW_LENGTH = 8.0  # under the head

MOTOR_HOLE_DIAMETER = 5.0
MOTOR_HOLE_HEIGHT = 10.0  # board's top face to the hole's centre

TAB_SCREW = SCREW_M5_COUNTERSUNK
TAB_THICKNESS = 5.0
TAB_WIDTH = 20.0  # along x
TAB_REACH = 16.0  # out from the wall's outer face

BOARD_PILLAR_DIAMETER = 4.0
# From the board's top-right corner seen from above, its corner at max x and
# max y, to each pillar's centre. Placed where the board has no parts.
BOARD_PILLAR_OFFSETS = ((-20.0, -5.0), (-5.0, -40.0), (-41.0, -41.0))
CLAMP_SQUEEZE = 0.2

CUT_OVERSHOOT = 0.5


def interior_length() -> float:
    return BOARD_ZONE_LENGTH


def interior_width() -> float:
    """The board across, plus its clearance to each long wall."""
    if LEDGE_WIDTH <= BOARD_CLEARANCE:
        raise ValueError(
            f"ledge width {LEDGE_WIDTH} does not reach past the board's "
            f"clearance {BOARD_CLEARANCE}, so the board would drop past it"
        )
    return BOARD_SIDE + 2 * BOARD_CLEARANCE


def outer_extent() -> tuple[float, float, float, float]:
    """The shoebox's rectangle in plan, as `(x0, x1, y0, y1)`, which the lid shares."""
    return (
        -WALL_THICKNESS,
        interior_length() + WALL_THICKNESS,
        -WALL_THICKNESS,
        interior_width() + WALL_THICKNESS,
    )


def post_half_side() -> float:
    """Half a lid post's side: the insert's boss radius, so the pocket has its wall all round."""
    return HeatInsert(spec=LID_INSERT).boss_radius


def post_points() -> tuple[tuple[float, float], ...]:
    """The four lid posts' centres, as `(x, y)`.

    Each post carries a long wall on past an end wall's outer face, its outer
    face flush with that long wall's, so the posts stand out along x only, the
    outline in plan reads as an H, and no post takes anything from the interior.
    """
    half = post_half_side()
    x0 = -WALL_THICKNESS - half
    x1 = interior_length() + WALL_THICKNESS + half
    y0, y1 = -WALL_THICKNESS + half, interior_width() + WALL_THICKNESS - half
    return ((x0, y0), (x1, y0), (x0, y1), (x1, y1))


def plan_rectangles() -> list[tuple[float, float, float, float]]:
    """The shoebox's outline in plan, as `(x0, x1, y0, y1)` rectangles: the walls' and each post's.

    The lid is cut to the same outline, so it covers the posts and nothing more.
    """
    half = post_half_side()
    return [outer_extent()] + [
        (x - half, x + half, y - half, y + half) for x, y in post_points()
    ]


def _connector_prototypes(material: Material) -> list[SidePanelMount]:
    """One RJ45 and one jack at the origin, built only to be measured."""
    origin = (0.0, 0.0, 0.0)
    facing = SidePanelFacing.X_POS
    return [
        RJ45KeystoneMount(
            at=origin,
            facing=facing,
            panel_thickness=WALL_THICKNESS,
            material=material,
        ),
        DCBarrelJackMount(
            at=origin,
            facing=facing,
            panel_thickness=WALL_THICKNESS,
            material=material,
        ),
    ]


def _cutout_centre(mount: SidePanelMount) -> float:
    """Height of a mount's cutout centre above its own channel floor."""
    box = mount.cutout().bounding_box()
    return (box.min.Z + box.max.Z) / 2


def connector_mounts(material: Material = Material.PLA) -> list[SidePanelMount]:
    """The RJ45 and the jack in the lower story, side by side across the connector wall.

    Every mount sits on the wall's inner face at `x = 0` facing `X_POS`, so its
    channel grows into the lower story and its cutout breaks out through the
    wall. The slack across the wall is split evenly into the three gaps.

    The jack is raised until its cutout's centre is level with the RJ45's, so
    the two openings line up across the wall.
    """
    rj45, jack = _connector_prototypes(material)
    jack_floor = FLOOR_THICKNESS + _cutout_centre(rj45) - _cutout_centre(jack)
    if jack_floor < FLOOR_THICKNESS:
        raise ValueError(
            f"the jack's cutout centre sits above the RJ45's, so lining them "
            f"up would sink the jack {FLOOR_THICKNESS - jack_floor} into the floor"
        )
    rj45_span = rj45.CHANNEL_WIDTH + 2 * rj45.sidewall_thickness
    jack_span = jack.CHANNEL_WIDTH + 2 * jack.sidewall_thickness
    gap = (interior_width() - rj45_span - jack_span) / 3
    if gap < 0.0:
        raise ValueError(
            f"the RJ45 and the jack need {rj45_span + jack_span} across the "
            f"connector wall, which is {interior_width()} wide"
        )
    return [
        RJ45KeystoneMount(
            at=(0.0, gap + rj45_span / 2, FLOOR_THICKNESS),
            facing=SidePanelFacing.X_POS,
            panel_thickness=WALL_THICKNESS,
            material=material,
        ),
        DCBarrelJackMount(
            at=(0.0, 2 * gap + rj45_span + jack_span / 2, jack_floor),
            facing=SidePanelFacing.X_POS,
            panel_thickness=WALL_THICKNESS,
            material=material,
        ),
    ]


@lru_cache(maxsize=None)
def ledge_top(material: Material = Material.PLA) -> float:
    """Where the board's underside rests: clear of the tallest channel or cutout by the leads' room."""
    tallest = FLOOR_THICKNESS
    for mount in connector_mounts(material):
        tallest = max(
            tallest,
            mount.body().bounding_box().max.Z,
            mount.cutout().bounding_box().max.Z,
        )
    return tallest + BOARD_UNDERSIDE_CLEARANCE


def board_top(material: Material = Material.PLA) -> float:
    return ledge_top(material) + BOARD_THICKNESS


def wall_top(material: Material = Material.PLA) -> float:
    """Top of the walls and posts, which is where the lid's underside lands."""
    return board_top(material) + UPPER_HEIGHT


def stop_spans() -> tuple[tuple[float, float], tuple[float, float]]:
    """The two stops that keep the board from sliding along x, as `(x0, x1)`, connector side first.

    Measured from the motor wall: the near stop's board side sits
    `STOP_MOTOR_WALL_DISTANCE` in from it, and the other stop sits `STOP_GAP`
    of clear space beyond.
    """
    near_x1 = interior_length() - STOP_MOTOR_WALL_DISTANCE + STOP_THICKNESS
    near_x0 = near_x1 - STOP_THICKNESS
    far_x1 = near_x0 - STOP_GAP
    far_x0 = far_x1 - STOP_THICKNESS
    if far_x0 < 0.0:
        raise ValueError(
            f"the connector-side stop starts at x {far_x0}, past the connector wall"
        )
    if STOP_GAP < BOARD_SIDE:
        raise ValueError(f"stop gap {STOP_GAP} is narrower than the board {BOARD_SIDE}")
    return ((far_x0, far_x1), (near_x0, near_x1))


def board_origin() -> tuple[float, float]:
    """The board's corner nearest the origin: centred between the stops, against its clearance in y."""
    (_, gap_start), (gap_end, _) = stop_spans()
    return ((gap_start + gap_end - BOARD_SIDE) / 2, BOARD_CLEARANCE)


def board_pillar_points() -> tuple[tuple[float, float], ...]:
    """Where the lid presses the board onto the ledge, as `(x, y)`."""
    bx, by = board_origin()
    corner_x, corner_y = bx + BOARD_SIDE, by + BOARD_SIDE
    return tuple((corner_x + dx, corner_y + dy) for dx, dy in BOARD_PILLAR_OFFSETS)
