from dataclasses import dataclass


@dataclass(frozen=True)
class RadialBearingSpec:
    """A radial bearing specification.

    Attributes:
        outer_diameter: The outer diameter of the bearing in millimeters.
        bore: The inner diameter of the bearing in millimeters, where the shaft goes.
        width: The width (height of the cylinder) of the bearing in millimeters.
    """

    outer_diameter: float
    bore: float
    width: float

    @property
    def od(self) -> float:
        return self.outer_diameter


BEARING_608 = RadialBearingSpec(outer_diameter=22.0, bore=8.0, width=7.0)
