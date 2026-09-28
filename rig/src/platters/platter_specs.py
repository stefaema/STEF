from dataclasses import dataclass


@dataclass(frozen=True)
class PlatterSpec:
    """A platter the film winds on, lying flat and turned from below.

    Attributes:
        thickness: how thick the plate is.
        centre_hole_diameter: the hole in the middle, which the cap fills.
        bolt_circle_radius: radius the mounting holes sit on.
        bolt_count: how many mounting holes there are.
    """

    thickness: float
    centre_hole_diameter: float
    bolt_circle_radius: float
    bolt_count: int


# Measured off a platter. The bolt circle came from the three holes'
# circumcentre, so it is a radius rather than a hole-to-hole distance.
PLATTER_360 = PlatterSpec(
    thickness=3.1,
    centre_hole_diameter=70.0,
    bolt_circle_radius=53.0,
    bolt_count=3,
)
