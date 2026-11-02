from typing import cast

from build123d import Cylinder, Part
from steppers.shaft_hub import END_DEPTH, ShaftHub

from rig.materials import Material
from rollers.film_roller import total_length
from rollers.motion import MOTION_ROLLERS

DIAMETER = 50.0


def build(material: Material = Material.PLA) -> Part:
    """A plain cylinder as long as the motion roller on the same ShaftHub."""
    length = total_length(MOTION_ROLLERS[0].gauges, END_DEPTH)
    core = ShaftHub(length=length, material=material, at=(0.0, 0.0, -length / 2))
    core.check_radius(DIAMETER / 2)
    return cast(Part, Cylinder(DIAMETER / 2, length) - core.cutters())
