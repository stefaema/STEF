from dataclasses import dataclass


@dataclass(frozen=True)
class RoundOringSpec:
    """A round-profile O-ring.

    Attributes:
        inner_diameter: ID, the diameter of the loop the rubber cord forms.
        outer_diameter: OD, the loop's diameter measured across the outside
            of the cord.
    """

    inner_diameter: float
    outer_diameter: float

    @property
    def cross_section_diameter(self) -> float:
        """The rubber cord's own thickness (a.k.a. CS or W), seen in profile."""
        return (self.outer_diameter - self.inner_diameter) / 2

    def outermost_points(self) -> tuple[float, float]:
        """Where the profile reaches its outermost extent, relative to its own center."""
        return (0.0, 0.0)

    def axial_reach(self) -> float:
        """How far the profile's material extends toward a wall it's seated against."""
        return self.cross_section_diameter / 2


@dataclass(frozen=True)
class SquareOringSpec:
    """A square-profile O-ring.

    Attributes:
        inner_diameter: ID, the diameter of the loop the rubber cord forms.
        outer_diameter: OD, the loop's diameter measured across the outside
            of the cord. Together with inner_diameter, gives the face's
            width by subtraction, same as RoundOringSpec.cross_section_diameter.
        height: the profile's radial thickness. A square cross-section
            doesn't share this with its width, so it's given directly.
    """

    inner_diameter: float
    outer_diameter: float
    height: float

    @property
    def width(self) -> float:
        """The face's width, seen in profile, along the contact band's axis."""
        return (self.outer_diameter - self.inner_diameter) / 2

    def outermost_points(self) -> tuple[float, float]:
        """Where the profile reaches its outermost extent, relative to its own center."""
        return (-self.width / 2, self.width / 2)

    def axial_reach(self) -> float:
        """How far the profile's material extends toward a wall it's seated against."""
        return self.width / 2


OringSpec = RoundOringSpec | SquareOringSpec
