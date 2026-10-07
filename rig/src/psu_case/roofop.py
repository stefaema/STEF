from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos, Rot
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK

from psu_case import seam, shoebox
from psu_case.psu_specs import PSU, PSUFace, PSUScrewHole, PSUSpecs
from psu_case.seam import PLATE_THICKNESS, SEAM_SCREW
from rig.materials import Material

SCREWS = {"M3": SCREW_M3_COUNTERSUNK}
INSERTS = {"M3": INSERT_M3_SHORT}

PAD_MARGIN = 1.0
CUT_OVERSHOOT = 0.5

CLAMP_PILLAR_DIAMETER = 8.0
CLAMP_SQUEEZE = 0.2


def _along_position(hole: PSUScrewHole, psu: PSUSpecs) -> float:
    return psu.length - hole.along


def _pad_radius(hole: PSUScrewHole, material: Material) -> float:
    if hole.is_tapped:
        return ScrewHole(spec=SCREWS[hole.thread]).head_radius + PAD_MARGIN
    return HeatInsert(spec=INSERTS[hole.thread], material=material).boss_radius


def _floor_cutter(hole: PSUScrewHole, psu: PSUSpecs, material: Material) -> Part:
    """A tapped hole is bored up from below; an untapped one takes an insert from above."""
    x, y = _along_position(hole, psu), hole.across
    if hole.is_tapped:
        screw = ScrewHole(spec=SCREWS[hole.thread], sink_head=True)
        return cast(
            Part,
            Pos(x, y, 0.0)
            * Rot(180.0, 0.0, 0.0)
            * screw.cutter(PLATE_THICKNESS + CUT_OVERSHOOT),
        )
    insert = HeatInsert(
        spec=INSERTS[hole.thread], facing=InsertFacing.DOWN, material=material
    )
    bore = PLATE_THICKNESS - insert.pocket_depth + CUT_OVERSHOOT
    return cast(Part, Pos(x, y, PLATE_THICKNESS) * insert.cutter(max(0.0, bore)))


def _seam_cutter() -> Part:
    screw = ScrewHole(spec=SEAM_SCREW, sink_head=True)
    return screw.cutter(PLATE_THICKNESS + CUT_OVERSHOOT)


def _clamp_pillars(psu: PSUSpecs, material: Material) -> Part:
    """Posts hanging under the plate that land on the connectors and trap them.

    A mount's `CLAMP_POINTS` are heights above the channel's own floor, and the
    channels stand on the tray floor, so the site's `z` and the plate's
    underside are quoted from one origin and the pillar is just the difference.
    Only the C14 and the jack bank declare any; the rocker and the Wagos want
    nothing pressing on them.
    """
    underside = shoebox.tray_height(material)
    pillars = Part()
    for x, y, z in shoebox.clamp_sites(psu, material):
        length = underside - z + CLAMP_SQUEEZE
        if length <= 0.0:
            raise ValueError(
                f"clamp site at ({x}, {y}, {z}) is at or above the plate's "
                f"underside {underside}, so no pillar can reach it"
            )
        pillars += Pos(x, y, -length) * Cylinder(
            CLAMP_PILLAR_DIAMETER / 2,
            length,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
    return cast(Part, pillars)


def build(material: Material = Material.PLA, psu: PSUSpecs = PSU) -> Part:
    """The plate the PSU bolts down onto, which is also the shoebox's ceiling.

    One face carries the PSU, the other closes the connector tray, and the skirt
    is what ties the two pieces together. It carries no cable opening: the PSU
    covers nearly all of it, so cables leave through the shoebox's side door.
    Pillars hang off its underside onto the connectors that ask to be clamped.
    """
    seam.check_clear_of_psu(psu)

    x0, x1, y0, y1 = seam.plate_extent(psu)
    plate = Pos(x0, y0, 0.0) * Box(
        x1 - x0, y1 - y0, PLATE_THICKNESS, align=(Align.MIN, Align.MIN, Align.MIN)
    )

    solid = cast(Part, plate) + _clamp_pillars(psu, material)
    for hole in psu.screw_holes:
        if hole.face is PSUFace.FLOOR:
            solid -= _floor_cutter(hole, psu, material)
    for x, y in seam.seam_points(psu):
        solid -= Pos(x, y, PLATE_THICKNESS) * _seam_cutter()
    return cast(Part, solid)
