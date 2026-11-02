from fasteners.heat_insert import HeatInsert
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK

from psu_case.psu_specs import PSU, PSUSpecs

SEAM_SCREW = SCREW_M3_COUNTERSUNK
SEAM_INSERT = INSERT_M3_SHORT

PLATE_THICKNESS = 6.0
SKIRT_MARGIN = 1.4


def skirt_width() -> float:
    """How far the plate runs past the PSU's footprint, set by the seam screw's head.

    The screw sits on the skirt's centreline, so half the skirt has to clear the
    countersink, and the shoebox's insert boss has to fit in that same half.
    """
    head = ScrewHole(spec=SEAM_SCREW).head_radius + SKIRT_MARGIN
    boss = HeatInsert(spec=SEAM_INSERT).boss_radius
    return 2 * max(head, boss)


def plate_extent(psu: PSUSpecs = PSU) -> tuple[float, float, float, float]:
    """Outline of the plate. It is the PSU footprint with a skirt added on three edges.

    The back edge stops flush at the PSU's back face, since the shoebox's back
    wall rises through that plane and there is nothing there to screw into.
    """
    skirt = skirt_width()
    return (-skirt, psu.length + skirt, -skirt, psu.width)


def seam_points(psu: PSUSpecs = PSU) -> tuple[tuple[float, float], ...]:
    """Where the plate screws down onto the shoebox's wall tops.

    Three across the front, the two corners and one between them, then one at
    the far end of each side. The back needs none: the PSU bolts to both pieces
    there and holds them together itself.
    """
    x0, x1, y0, _ = plate_extent(psu)
    half = skirt_width() / 2
    left, right, front = x0 + half, x1 - half, y0 + half
    back = psu.width - half
    return (
        (left, front),
        ((left + right) / 2, front),
        (right, front),
        (left, back),
        (right, back),
    )


def check_clear_of_psu(psu: PSUSpecs = PSU) -> None:
    """No seam screw may sit under the PSU.

    The plate is bolted to the PSU first and the pair of them to the shoebox
    second, so by the time a seam screw is driven, anything inside the PSU's
    footprint is under the PSU and cannot be reached.
    """
    radius = ScrewHole(spec=SEAM_SCREW).head_radius
    for x, y in seam_points(psu):
        dx = max(0.0 - x, x - psu.length, 0.0)
        dy = max(0.0 - y, y - psu.width, 0.0)
        if (dx * dx + dy * dy) ** 0.5 <= radius:
            raise ValueError(
                f"seam screw at ({x}, {y}) falls under the PSU's footprint, "
                f"where a driver cannot reach it once the PSU is bolted down"
            )
