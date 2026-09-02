from typing import cast

from bearings.core import BearingCore
from bearings.seat import BearingSeat
from build123d import Part

from pulleys.pulley import DRIVE_PULLEY
from rig.materials import Material

BOSS_EXTENSION = 3.0


def sample(material: Material = Material.PLA) -> Part:
    seat = BearingSeat(material=material)
    seat.check_radius(DRIVE_PULLEY.band.root_radius)

    core = BearingCore(
        length=DRIVE_PULLEY.height + 2 * BOSS_EXTENSION,
        seat=seat,
        at=(0.0, 0.0, -BOSS_EXTENSION),
    )
    return cast(Part, (DRIVE_PULLEY.build() + core.body()) - core.cutters())
