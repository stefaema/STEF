from functools import lru_cache
from typing import cast

from build123d import Align, Axis, Box, Part, Pos, Rot, fillet
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK, SCREW_M5_COUNTERSUNK
from mounts import dc_barrel_jack, rocker_switch, wago_222
from mounts.c14 import C14Mount
from mounts.dc_barrel_jack import DCBarrelJackMount
from mounts.rocker_switch import RockerSwitchMount
from mounts.side_panel import SidePanelFacing, SidePanelMount
from mounts.wago_222 import Wago222Mount
from mounts.wago_pair import WagoPair

from psu_case import case, seam
from psu_case.mount_zone import MountZone, ResolvedLayout
from psu_case.psu_specs import PSU, PSUFace, PSUScrewHole, PSUSpecs
from rig.materials import Material

SCREWS = {"M3": SCREW_M3_COUNTERSUNK}
INSERTS = {"M3": INSERT_M3_SHORT}

FLOOR_THICKNESS = 6.0
CEILING = 3.0

MOUNT_SCREW = SCREW_M5_COUNTERSUNK
MOUNT_SCREW_MARGIN = 2.0
MOUNT_SPAN_FRACTION = 0.6
BACK_WALL_FILLET = 5.0
BACK_WALL_CROWN = 3.0

JACK_PANEL_THICKNESS = 3.0
JACK_RELIEF_MARGIN = 2.0
JACK_RELIEF_HEADROOM = 2.0

C14_RELIEF_MARGIN = 2.0

DOOR_SPAN_FRACTION = 0.25
DOOR_RISE_FRACTION = 1.0 / 3.0

CHIMNEY_SCREW = SCREW_M3_COUNTERSUNK
CHIMNEY_FRAME_INSET = 6.75
CHIMNEY_SCREW_HEIGHTS = (8.0, 30.0)

CUT_OVERSHOOT = 0.5

FRONT_PANEL_ITEMS = ("jack_bank", "c14", "rocker")


def wall_thickness() -> float:
    """The walls carry the seam screws, so the plate's skirt above them sets their thickness."""
    return seam.skirt_width()


def _front_panel_prototypes(material: Material) -> list[SidePanelMount]:
    """One of each front-wall mount at the origin, built only to be measured."""
    origin = (0.0, 0.0, 0.0)
    facing = SidePanelFacing.X_POS
    return [
        C14Mount(at=origin, facing=facing, panel_thickness=wall_thickness()),
        RockerSwitchMount(
            at=origin,
            facing=facing,
            panel_thickness=wall_thickness(),
            sidewall_thickness=rocker_switch.SIDEWALL_THICKNESS[material],
            material=material,
        ),
        DCBarrelJackMount(
            at=origin,
            facing=facing,
            panel_thickness=wall_thickness(),
            material=material,
        ),
    ]


@lru_cache(maxsize=None)
def interior_height(material: Material = Material.PLA) -> float:
    """Clear height inside the tray.

    The tallest channel is one demand. The other is that the tallest cutout
    still leaves `CEILING` of wall above it, which the rocker's does not at the
    channel height alone: it reaches 29 in a 30 channel.
    """
    tallest = case.minimum_height()
    for mount in _front_panel_prototypes(material):
        tallest = max(tallest, mount.cutout().bounding_box().max.Z + CEILING)
    return tallest


def tray_height(material: Material = Material.PLA) -> float:
    """Top of the walls, which is where the plate lands."""
    return FLOOR_THICKNESS + interior_height(material)


def seam_height(material: Material = Material.PLA) -> float:
    """Top of the plate once it is seated, which is the PSU's underside."""
    return tray_height(material) + seam.PLATE_THICKNESS


def mount_screw_height(psu: PSUSpecs = PSU, material: Material = Material.PLA) -> float:
    """Where the two M5s sit, clear above the PSU rather than beside it."""
    head = ScrewHole(spec=MOUNT_SCREW).head_radius
    return seam_height(material) + psu.height + head + MOUNT_SCREW_MARGIN


def back_wall_top(psu: PSUSpecs = PSU, material: Material = Material.PLA) -> float:
    """Top of the back wall: the PSU's full height, plus room for the M5 heads."""
    head = ScrewHole(spec=MOUNT_SCREW).head_radius
    return (
        mount_screw_height(psu, material) + head + MOUNT_SCREW_MARGIN + BACK_WALL_CROWN
    )


def mount_points(
    psu: PSUSpecs = PSU, material: Material = Material.PLA
) -> tuple[tuple[float, float], ...]:
    """The two M5 positions on the back wall, as `(x, z)`, spread about its centre."""
    x0, x1, _, _ = outer_extent(psu)
    centre = (x0 + x1) / 2
    half = (x1 - x0) * MOUNT_SPAN_FRACTION / 2
    z = mount_screw_height(psu, material)
    return ((centre - half, z), (centre + half, z))


def outer_extent(psu: PSUSpecs = PSU) -> tuple[float, float, float, float]:
    """The box's rectangle: the plate's, carried back over the back wall."""
    x0, x1, y0, _ = seam.plate_extent(psu)
    return (x0, x1, y0, psu.width + wall_thickness())


def _floor(psu: PSUSpecs) -> Part:
    x0, x1, y0, y1 = outer_extent(psu)
    return cast(
        Part,
        Pos(x0, y0, 0.0)
        * Box(
            x1 - x0, y1 - y0, FLOOR_THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN)
        ),
    )


def _walls(psu: PSUSpecs, material: Material) -> Part:
    """Front, left and right up to the plate; the back carries on past it.

    Every wall is one thickness, the back included over its whole height, so the
    box is a plain rectangle in plan and the PSU's back face bears on one plane
    from the tray floor to the top.
    """
    x0, x1, y0, y1 = outer_extent(psu)
    wall = wall_thickness()
    height = tray_height(material)

    def slab(
        at_x: float, at_y: float, length: float, width: float, tall: float
    ) -> Part:
        return cast(
            Part,
            Pos(at_x, at_y, 0.0)
            * Box(length, width, tall, align=(Align.MIN, Align.MIN, Align.MIN)),
        )

    return cast(
        Part,
        slab(x0, y0, x1 - x0, wall, height)
        + slab(x0, y0, wall, y1 - y0, height)
        + slab(x1 - wall, y0, wall, y1 - y0, height)
        + _back_wall(psu, material),
    )


def _back_wall(psu: PSUSpecs, material: Material) -> Part:
    """The back, full height and one thickness, rounded where it stands proud.

    It is built whole and filleted before anything else touches it, so the
    rounding picks up its own two top corners and not an edge of some
    neighbouring wall.
    """
    x0, x1, _, _ = outer_extent(psu)
    slab = Pos(x0, psu.width, 0.0) * Box(
        x1 - x0,
        wall_thickness(),
        back_wall_top(psu, material),
        align=(Align.MIN, Align.MIN, Align.MIN),
    )
    crown = slab.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1]
    return cast(Part, fillet(crown, BACK_WALL_FILLET))


def _mount_cutters(psu: PSUSpecs, material: Material) -> Part:
    """The two M5s, sunk on the face the PSU bears against and bored straight out."""
    screw = ScrewHole(spec=MOUNT_SCREW, sink_head=True)
    cutters = Part()
    for x, z in mount_points(psu, material):
        cutters += (
            Pos(x, psu.width, z)
            * Rot(90.0, 0.0, 0.0)
            * screw.cutter(wall_thickness() + CUT_OVERSHOOT)
        )
    return cutters


def door(psu: PSUSpecs = PSU, material: Material = Material.PLA) -> tuple[float, ...]:
    """The cable opening in the right wall, as `(y0, y1, z0, z1)`.

    Its sill is the tray floor, so cables run straight out rather than over a
    lip, and it is centred across the wall. Given as fractions of the wall it
    sits in, so it re-solves with the PSU like everything else.
    """
    width = psu.width * DOOR_SPAN_FRACTION
    rise = interior_height(material) * DOOR_RISE_FRACTION
    centre = psu.width / 2
    return (
        centre - width / 2,
        centre + width / 2,
        FLOOR_THICKNESS,
        FLOOR_THICKNESS + rise,
    )


def chimney_seam_points(
    psu: PSUSpecs = PSU, material: Material = Material.PLA
) -> tuple[tuple[float, float], ...]:
    """Where the chimney bolts to the right wall's outer face, as `(y, z)`.

    Offset in both axes rather than levelled. A level pair would leave the
    chimney's tipping load to the flange's clamp force, which a printed part
    sheds as it creeps; staggering them carries that load as a couple in the
    screws instead. Both sit beside the door, since the 6mm under the sill
    cannot hold an insert's boss.
    """
    y0, y1, _, _ = door(psu, material)
    low, high = CHIMNEY_SCREW_HEIGHTS
    return (
        (y0 - CHIMNEY_FRAME_INSET, low),
        (y1 + CHIMNEY_FRAME_INSET, high),
    )


def _door_cutter(psu: PSUSpecs, material: Material) -> Part:
    y0, y1, z0, z1 = door(psu, material)
    wall = wall_thickness()
    return cast(
        Part,
        Pos(psu.length - CUT_OVERSHOOT, y0, z0)
        * Box(
            wall + 2 * CUT_OVERSHOOT,
            y1 - y0,
            z1 - z0,
            align=(Align.MIN, Align.MIN, Align.MIN),
        ),
    )


def _chimney_inserts(psu: PSUSpecs, material: Material) -> Part:
    """Pockets in the right wall's outer face, driven in along -X."""
    insert = HeatInsert(
        spec=INSERTS[CHIMNEY_SCREW.thread.designation],
        facing=InsertFacing.DOWN,
        material=material,
    )
    face = psu.length + wall_thickness()
    cutters = Part()
    for y, z in chimney_seam_points(psu, material):
        cutters += Pos(face, y, z) * Rot(0.0, 90.0, 0.0) * insert.cutter()
    return cutters


def _seam_inserts(psu: PSUSpecs, material: Material) -> Part:
    """The pockets in the wall tops that take the plate's screws."""
    insert = HeatInsert(
        spec=INSERTS[seam.SEAM_SCREW.thread.designation],
        facing=InsertFacing.DOWN,
        material=material,
    )
    cutters = Part()
    for x, y in seam.seam_points(psu):
        cutters += Pos(x, y, tray_height(material)) * insert.cutter()
    return cutters


def _back_cutter(hole: PSUScrewHole, psu: PSUSpecs, material: Material) -> Part:
    """One of the PSU's back-face holes, driven into the riser from outside."""
    x = psu.length - hole.along
    z = seam_height(material) + hole.across
    face = psu.width
    if hole.is_tapped:
        screw = ScrewHole(spec=SCREWS[hole.thread], sink_head=True)
        return cast(
            Part,
            Pos(x, face + wall_thickness(), z)
            * Rot(-90.0, 0.0, 0.0)
            * screw.cutter(wall_thickness() + CUT_OVERSHOOT),
        )
    insert = HeatInsert(
        spec=INSERTS[hole.thread], facing=InsertFacing.DOWN, material=material
    )
    bore = wall_thickness() - insert.pocket_depth + CUT_OVERSHOOT
    return cast(
        Part,
        Pos(x, face, z) * Rot(90.0, 0.0, 0.0) * insert.cutter(max(0.0, bore)),
    )


def _resolved(psu: PSUSpecs, material: Material) -> dict[str, ResolvedLayout]:
    x0, x1, y0, y1 = outer_extent(psu)
    return MountZone.solve(
        case.front_panel_layout(material),
        case.distance_layout_3wago(),
        case.distance_layout_5wago_pair(),
        structure_width=x1 - x0,
        structure_depth=y1 - y0,
        front_panel_thickness=wall_thickness(),
        case_wall_thickness=wall_thickness(),
    )


def relief_depth() -> float:
    """How far the jack bank's groove is sunk into the front wall's outer face.

    A barrel jack threads through the panel and takes a nut on the outside, and
    the wall is as thick as the plate's skirt needs, which is more thread than
    the jack has. The groove gives the jacks back the `JACK_PANEL_THICKNESS`
    their own sample was fitted against.
    """
    return wall_thickness() - JACK_PANEL_THICKNESS


def _jack_bank(
    front_panel: ResolvedLayout, material: Material
) -> list[DCBarrelJackMount]:
    bank_start = (
        front_panel.centers[case.JACK_BANK_INDEX]
        - front_panel.spans[case.JACK_BANK_INDEX] / 2
    )
    jack_width = dc_barrel_jack.CHANNEL_WIDTH[material]
    return DCBarrelJackMount.bank(
        at=(bank_start + jack_width / 2, 0.0, FLOOR_THICKNESS),
        facing=SidePanelFacing.Y_POS,
        panel_thickness=JACK_PANEL_THICKNESS,
        count=case.DC_JACK_COUNT,
        growing_toward=SidePanelFacing.X_POS,
        material=material,
    )


def _jack_relief(front_panel: ResolvedLayout, material: Material) -> Part:
    """The groove across the front wall's outer face that the jacks' nuts land in.

    Cut from the outside, so the bank still stands on the wall's inner face and a
    jack drops into its channel the way its sample was fitted. Bounded in X by the
    bank's own sidewalls and in Z by its channel, which leaves the wall at full
    thickness everywhere the seam screws land: those sit at the wall top, far
    above this groove's ceiling.

    It runs to the ground rather than stopping at the tray floor. A jack's nut
    turns below the hole's centreline as much as above it, and a floor level with
    the tray's would leave only the channel's own half-height to turn it in. The
    cost is the plinth: over this span the wall meets the ground at
    `JACK_PANEL_THICKNESS`, braced by the bank's channel walls behind it.
    """
    bodies = Part()
    for mount in _jack_bank(front_panel, material):
        bodies += mount.body()
    bounds = bodies.bounding_box()

    return cast(
        Part,
        Pos(
            bounds.min.X - JACK_RELIEF_MARGIN,
            -wall_thickness() - CUT_OVERSHOOT,
            -CUT_OVERSHOOT,
        )
        * Box(
            (bounds.max.X - bounds.min.X) + 2 * JACK_RELIEF_MARGIN,
            relief_depth() + CUT_OVERSHOOT,
            FLOOR_THICKNESS
            + DCBarrelJackMount.CHANNEL_HEIGHT
            + JACK_RELIEF_HEADROOM
            + CUT_OVERSHOOT,
            align=(Align.MIN, Align.MIN, Align.MIN),
        ),
    )


def _c14_mount(front_panel: ResolvedLayout) -> C14Mount:
    return C14Mount(
        at=(front_panel.centers[case.C14_INDEX], 0.0, FLOOR_THICKNESS),
        facing=SidePanelFacing.Y_POS,
        panel_thickness=wall_thickness(),
    )


def _c14_relief(front_panel: ResolvedLayout) -> Part:
    bounds = _c14_mount(front_panel).cutout().bounding_box()
    return cast(
        Part,
        Pos(
            bounds.min.X - C14_RELIEF_MARGIN,
            -wall_thickness() - CUT_OVERSHOOT,
            -CUT_OVERSHOOT,
        )
        * Box(
            (bounds.max.X - bounds.min.X) + 2 * C14_RELIEF_MARGIN,
            relief_depth() + CUT_OVERSHOOT,
            bounds.max.Z + C14_RELIEF_MARGIN + CUT_OVERSHOOT,
            align=(Align.MIN, Align.MIN, Align.MIN),
        ),
    )


def _front_panel_mounts(
    front_panel: ResolvedLayout, material: Material
) -> list[SidePanelMount]:
    """The connector row along the front wall, all facing `Y_POS`.

    Every mount sits on the wall's inner face at `y = 0` facing `Y_POS`, so its
    channel grows back into the tray and its cutout breaks out through the wall.
    The jack bank's cutout only has to clear `JACK_PANEL_THICKNESS`, since the
    groove takes the rest of the wall away from the outside.
    """
    wall = wall_thickness()
    floor = FLOOR_THICKNESS

    mounts: list[SidePanelMount] = list(_jack_bank(front_panel, material))
    mounts.append(_c14_mount(front_panel))
    mounts.append(
        RockerSwitchMount(
            at=(front_panel.centers[case.ROCKER_INDEX], 0.0, floor),
            facing=SidePanelFacing.Y_POS,
            panel_thickness=wall,
            sidewall_thickness=rocker_switch.SIDEWALL_THICKNESS[material],
            material=material,
        )
    )
    return mounts


def clamp_sites(
    psu: PSUSpecs = PSU, material: Material = Material.PLA
) -> tuple[tuple[float, float, float], ...]:
    """Where something from above has to press to trap a connector, as `(x, y, z)`.

    Each mount declares its own `CLAMP_POINTS` relative to the channel it sits
    in, and the channels sit on the tray floor, so `z` here already counts that
    floor. The plate's pillars are sized against `tray_height`, which is
    measured from the same origin, so the floor cancels out of the difference.
    """
    front_panel = _resolved(psu, material)["front_panel"]
    return tuple(
        (point.X, point.Y, point.Z)
        for mount in _front_panel_mounts(front_panel, material)
        for point in mount.clamp_points()
    )


def _wago_holders(psu: PSUSpecs, front_panel: ResolvedLayout) -> Part:
    """The Wagos, each sharing the centreline of the connector it feeds.

    Neither carries a cutout, so only the footprint matters. The 3-wire one
    stands against the back wall opening toward the C14, on the C14's own X. The
    5-wire pair opens along X, so its shared back runs along Y and lands on the
    jack bank's centreline; it floats between the bank's channels and the back
    wall, since a back-to-back pair has no end to stand against.
    """
    pair = WagoPair(
        at=(
            front_panel.centers[case.JACK_BANK_INDEX],
            _pair_centre_depth(psu),
            FLOOR_THICKNESS,
        ),
        channel_width=wago_222.CHANNEL_WIDTH_5CABLE,
        facing=SidePanelFacing.X_POS,
    )
    single = Wago222Mount(
        at=(front_panel.centers[case.C14_INDEX], psu.width, FLOOR_THICKNESS),
        facing=SidePanelFacing.Y_NEG,
        channel_width=wago_222.CHANNEL_WIDTH_3CABLE,
    )
    return cast(Part, pair.body() + single.body())


def _pair_centre_depth(psu: PSUSpecs) -> float:
    """Halfway between where the jack bank's channels end and the back wall."""
    return (DCBarrelJackMount.CHANNEL_LENGTH + psu.width) / 2


def build(material: Material = Material.PLA, psu: PSUSpecs = PSU) -> Part:
    """The lower story: connectors on the front, a back wall for the PSU, open on top.

    The top is left to `roofop`, which screws into the wall tops. Cables leave
    by the right wall's door and climb the outside of that wall to the PSU's
    terminals, which is why the plate itself carries no opening.
    """
    resolved = _resolved(psu, material)
    front_panel = resolved["front_panel"]

    bodies, cutouts = Part(), Part()
    for mount in _front_panel_mounts(front_panel, material):
        bodies += mount.body()
        cutouts += mount.cutout()

    solid = _floor(psu) + _walls(psu, material) + bodies
    solid += _wago_holders(psu, front_panel)

    solid -= _jack_relief(front_panel, material)
    solid -= _c14_relief(front_panel)
    solid -= cutouts
    solid -= _door_cutter(psu, material)
    solid -= _seam_inserts(psu, material)
    solid -= _chimney_inserts(psu, material)
    solid -= _mount_cutters(psu, material)
    for hole in psu.screw_holes:
        if hole.face is PSUFace.BACK:
            solid -= _back_cutter(hole, psu, material)
    return cast(Part, solid)
