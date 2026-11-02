from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos, Rot
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK

from psu_case.psu_specs import PSU, PSUFace, PSUScrewHole, PSUSpecs
from rig.materials import Material

SCREWS = {"M3": SCREW_M3_COUNTERSUNK}
INSERTS = {"M3": INSERT_M3_SHORT}

FLOOR_THICKNESS = 6.0
BAND_WIDTH = 12.0
RIB_WIDTH = 6.0
PAD_MARGIN = 1.0

RIM_THICKNESS = 3.0
RIM_HEIGHT = 6.0

BACK_WALL_DEPTH = 6.0
PILLAR_MARGIN = 1.0
PILLAR_HEADROOM = 2.0

CUT_OVERSHOOT = 0.5


def _floor_position(hole: PSUScrewHole, psu: PSUSpecs) -> tuple[float, float]:
    """Where a floor hole lands in the coupon's own frame.

    `along` is measured from the corner opposite the coupon's X origin, so it
    counts back from the far end rather than out from X zero.
    """
    return (_along_position(hole, psu), hole.across)


def _along_position(hole: PSUScrewHole, psu: PSUSpecs) -> float:
    """X a hole sits at, for either face.

    `along` is measured from the end opposite the coupon's X origin, and both
    faces are measured from that same corner, so one rule serves both.
    """
    return psu.length - hole.along


def _back_plane(psu: PSUSpecs) -> float:
    """Y the PSU's back face stands against.

    `across` is measured from the front-right corner, so the right edge is the
    origin and the back is the far one, a full width away from it.
    """
    return psu.width


def _boss_radius(hole: PSUScrewHole, material: Material) -> float:
    """Solid radius the coupon needs around this hole, whichever fastening it takes."""
    if hole.is_tapped:
        return ScrewHole(spec=SCREWS[hole.thread]).head_radius + PAD_MARGIN
    return (
        HeatInsert(spec=INSERTS[hole.thread], material=material).boss_radius
        + PAD_MARGIN
    )


def _floor_cutter(hole: PSUScrewHole, psu: PSUSpecs, material: Material) -> Part:
    """The cut at a floor hole. Tapped holes get a countersunk bore from below, and the others get an insert pocket from above."""
    x, y = _floor_position(hole, psu)
    if hole.is_tapped:
        screw = ScrewHole(spec=SCREWS[hole.thread], sink_head=True)
        return cast(
            Part,
            Pos(x, y, 0.0)
            * Rot(180.0, 0.0, 0.0)
            * screw.cutter(FLOOR_THICKNESS + CUT_OVERSHOOT),
        )
    insert = HeatInsert(
        spec=INSERTS[hole.thread], facing=InsertFacing.DOWN, material=material
    )
    bore = FLOOR_THICKNESS - insert.pocket_depth + CUT_OVERSHOOT
    return cast(Part, Pos(x, y, FLOOR_THICKNESS) * insert.cutter(max(0.0, bore)))


def _back_cutter(hole: PSUScrewHole, psu: PSUSpecs, material: Material) -> Part:
    """Same for a back-wall hole, turned to run along Y instead of Z."""
    face = _back_plane(psu)
    height = FLOOR_THICKNESS + hole.across
    if hole.is_tapped:
        screw = ScrewHole(spec=SCREWS[hole.thread], sink_head=True)
        return cast(
            Part,
            Pos(_along_position(hole, psu), face + BACK_WALL_DEPTH, height)
            * Rot(-90.0, 0.0, 0.0)
            * screw.cutter(BACK_WALL_DEPTH + CUT_OVERSHOOT),
        )
    insert = HeatInsert(
        spec=INSERTS[hole.thread], facing=InsertFacing.DOWN, material=material
    )
    bore = BACK_WALL_DEPTH - insert.pocket_depth + CUT_OVERSHOOT
    return cast(
        Part,
        Pos(_along_position(hole, psu), face, height)
        * Rot(90.0, 0.0, 0.0)
        * insert.cutter(max(0.0, bore)),
    )


def _pad(hole: PSUScrewHole, psu: PSUSpecs, material: Material) -> Part:
    x, y = _floor_position(hole, psu)
    return cast(
        Part,
        Pos(x, y, 0.0)
        * Cylinder(
            _boss_radius(hole, material),
            FLOOR_THICKNESS,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        ),
    )


def _rib(
    hole: PSUScrewHole, psu: PSUSpecs, bounds: tuple[float, float, float, float]
) -> Part:
    """A tie from a floor pad to the nearest edge of the perimeter band.

    Nothing is drawn for a pad the band already reaches.
    """
    inner_x0, inner_x1, inner_y0, inner_y1 = bounds
    x, y = _floor_position(hole, psu)
    runs = {
        x - inner_x0: (inner_x0, y - RIB_WIDTH / 2, x - inner_x0, RIB_WIDTH),
        inner_x1 - x: (x, y - RIB_WIDTH / 2, inner_x1 - x, RIB_WIDTH),
        y - inner_y0: (x - RIB_WIDTH / 2, inner_y0, RIB_WIDTH, y - inner_y0),
        inner_y1 - y: (x - RIB_WIDTH / 2, y, RIB_WIDTH, inner_y1 - y),
    }
    reach = min(runs)
    if reach <= 0.0:
        return Part()
    start_x, start_y, length, width = runs[reach]
    return cast(
        Part,
        Pos(start_x, start_y, 0.0)
        * Box(length, width, FLOOR_THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN)),
    )


def _pillar(hole: PSUScrewHole, psu: PSUSpecs, material: Material) -> Part:
    """A section of the back wall raised high enough to reach one hole. Its size depends only on that hole.

    It shares the wall's depth, so it adds height over a hole and nothing else.
    """
    radius = _boss_radius(hole, material)
    width = 2 * (radius + PILLAR_MARGIN)
    top = FLOOR_THICKNESS + hole.across + radius + PILLAR_HEADROOM
    return cast(
        Part,
        Pos(_along_position(hole, psu), _back_plane(psu), 0.0)
        * Box(width, BACK_WALL_DEPTH, top, align=(Align.CENTER, Align.MIN, Align.MIN)),
    )


def _extent(psu: PSUSpecs) -> tuple[float, float, float, float]:
    """Outer rectangle of the coupon. It covers the PSU footprint and everything around it."""
    return (
        -RIM_THICKNESS,
        psu.length + RIM_THICKNESS,
        -RIM_THICKNESS,
        _back_plane(psu) + BACK_WALL_DEPTH,
    )


def _band_bounds(psu: PSUSpecs) -> tuple[float, float, float, float]:
    """Inner edge of the perimeter band. The ribs connect to it."""
    x0, x1, y0, y1 = _extent(psu)
    return (x0 + BAND_WIDTH, x1 - BAND_WIDTH, y0 + BAND_WIDTH, y1 - BAND_WIDTH)


def _floor(psu: PSUSpecs, material: Material) -> Part:
    """The open frame that the PSU sits on. It is a perimeter band with a pad at each hole and ribs that connect the pads to the band."""
    x0, x1, y0, y1 = _extent(psu)
    inner_x0, inner_x1, inner_y0, inner_y1 = _band_bounds(psu)

    band = Pos(x0, y0, 0.0) * Box(
        x1 - x0, y1 - y0, FLOOR_THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN)
    ) - Pos(inner_x0, inner_y0, -CUT_OVERSHOOT) * Box(
        inner_x1 - inner_x0,
        inner_y1 - inner_y0,
        FLOOR_THICKNESS + 2 * CUT_OVERSHOOT,
        align=(Align.MIN, Align.MIN, Align.MIN),
    )

    solid = cast(Part, band)
    for hole in psu.screw_holes:
        if hole.face is not PSUFace.FLOOR:
            continue
        solid += _pad(hole, psu, material) + _rib(hole, psu, _band_bounds(psu))
    return solid


def _wall(at_x: float, at_y: float, length: float, width: float) -> Part:
    return cast(
        Part,
        Pos(at_x, at_y, FLOOR_THICKNESS)
        * Box(length, width, RIM_HEIGHT, align=(Align.MIN, Align.MIN, Align.MIN)),
    )


def _rims(psu: PSUSpecs) -> Part:
    """Three low walls along the free edges of the footprint. They guide the PSU into place.

    The PSU rests against the fourth edge, which `_back_wall` builds.
    """
    x0, x1, y0, y1 = _extent(psu)
    return cast(
        Part,
        _wall(x0, y0, RIM_THICKNESS, y1 - y0)
        + _wall(psu.length, y0, RIM_THICKNESS, y1 - y0)
        + _wall(x0, y0, x1 - x0, RIM_THICKNESS),
    )


def _back_wall(psu: PSUSpecs) -> Part:
    """The face the PSU's back bears on, continuous along its whole length.

    It carries the same depth as the pillars, so the bearing surface is one
    plane whether or not a screw hole is nearby.
    """
    x0, x1, _, _ = _extent(psu)
    return _wall(x0, _back_plane(psu), x1 - x0, BACK_WALL_DEPTH)


def sample(material: Material = Material.PLA, psu: PSUSpecs = PSU) -> Part:
    """A coupon that proves the PSU's screw pattern before any case is printed.

    Both faces that carry holes are checked against each other in one part, which
    is what measuring them apart cannot do: the PSU drops into the floor frame,
    and the back pillars have to line up at the same time.
    """
    solid = _floor(psu, material) + _rims(psu) + _back_wall(psu)
    for hole in psu.screw_holes:
        if hole.face is PSUFace.BACK:
            solid += _pillar(hole, psu, material)

    for hole in psu.screw_holes:
        solid -= (
            _floor_cutter(hole, psu, material)
            if hole.face is PSUFace.FLOOR
            else _back_cutter(hole, psu, material)
        )
    return cast(Part, solid)
