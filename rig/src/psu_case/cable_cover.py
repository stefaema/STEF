from typing import cast

from build123d import Align, Box, Part, Pos, Rot
from fasteners.screw import ScrewHole

from psu_case import shoebox
from psu_case.psu_specs import PSU, PSUSpecs
from rig.materials import Material

WALL_THICKNESS = 3.0
FLANGE_THICKNESS = 4.0
FLANGE_WIDTH = 12.0
INNER_DEPTH = 12.0
EXIT_RISE = 8.0

CUT_OVERSHOOT = 0.5


def outer_depth() -> float:
    """How far the chimney stands off the wall, cable room plus its front wall."""
    return INNER_DEPTH + WALL_THICKNESS


def wall_face(psu: PSUSpecs = PSU) -> float:
    """The right wall's outer face, which the flange lies on."""
    return psu.length + shoebox.wall_thickness()


def top(material: Material = Material.PLA) -> float:
    """Where cables leave, above the seam so they clear the plate's edge.

    The duct passes the seam plane and keeps going, so its exit opens beside the
    PSU rather than under it.
    """
    return shoebox.seam_height(material) + EXIT_RISE


def _flange(psu: PSUSpecs, material: Material) -> Part:
    """The plate that lies on the wall, stopping where the wall does.

    It runs only as high as the wall it bears on. Above that the duct carries on
    with nothing behind it, so a flange there would be a fin in open air.
    """
    y0, y1, _, _ = shoebox.door(psu, material)
    return cast(
        Part,
        Pos(wall_face(psu), y0 - FLANGE_WIDTH, 0.0)
        * Box(
            FLANGE_THICKNESS,
            (y1 - y0) + 2 * FLANGE_WIDTH,
            shoebox.tray_height(material),
            align=(Align.MIN, Align.MIN, Align.MIN),
        ),
    )


def _duct(psu: PSUSpecs, material: Material) -> Part:
    y0, y1, _, _ = shoebox.door(psu, material)
    return cast(
        Part,
        Pos(wall_face(psu), y0 - WALL_THICKNESS, 0.0)
        * Box(
            outer_depth(),
            (y1 - y0) + 2 * WALL_THICKNESS,
            top(material),
            align=(Align.MIN, Align.MIN, Align.MIN),
        ),
    )


def _bore(psu: PSUSpecs, material: Material) -> Part:
    """The cable way: open at the back onto the door, open at the top.

    One cut does both openings. Its floor is the door's sill, so a cable leaves
    the tray and turns upward without a lip to climb.
    """
    y0, y1, z0, _ = shoebox.door(psu, material)
    face = wall_face(psu)
    return cast(
        Part,
        Pos(face - CUT_OVERSHOOT, y0, z0)
        * Box(
            INNER_DEPTH + CUT_OVERSHOOT,
            y1 - y0,
            top(material) - z0 + CUT_OVERSHOOT,
            align=(Align.MIN, Align.MIN, Align.MIN),
        ),
    )


def _screw_cutters(psu: PSUSpecs, material: Material) -> Part:
    """Countersunk clearance holes onto the wall's two inserts.

    They sit outboard of the duct's side walls, so a driver reaches them square
    on rather than down the cable way.
    """
    screw = ScrewHole(spec=shoebox.CHIMNEY_SCREW, sink_head=True)
    outer = wall_face(psu) + FLANGE_THICKNESS
    cutters = Part()
    for y, z in shoebox.chimney_seam_points(psu, material):
        cutters += (
            Pos(outer, y, z)
            * Rot(0.0, 90.0, 0.0)
            * screw.cutter(FLANGE_THICKNESS + CUT_OVERSHOOT)
        )
    return cutters


def build(material: Material = Material.PLA, psu: PSUSpecs = PSU) -> Part:
    """The chimney that carries cables from the tray up to the PSU's terminals.

    An open-backed duct: the case's own wall closes it below the seam, and above
    the seam that open back is the exit. It bolts to the shoebox alone, so the
    plate and the PSU still lift straight off with it in place.
    """
    solid = _flange(psu, material) + _duct(psu, material)
    solid -= _bore(psu, material)
    solid -= _screw_cutters(psu, material)
    return cast(Part, solid)
