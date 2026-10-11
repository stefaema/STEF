from dataclasses import dataclass


@dataclass(frozen=True)
class NemaStepperSpec:
    """A NEMA stepper, measured as the face it bolts against.

    Everything here is what a plate carrying the motor has to answer to.

    Attributes:
        face_size: the square face's side, so also the widest a plate matching
            the motor can be.
        bolt_spacing: centre to centre of the four mounting holes, on a square.
        boss_diameter: OD of the raised ring around the shaft, which the plate
            must clear rather than sit on.
        shaft_diameter: the round shaft's OD.
        shaft_flat_depth: how deep the flat ground along the shaft (a.k.a. a
            D-cut) is, measured in from the round.
        shaft_length: how far the shaft stands out of the mounting face.
    """

    face_size: float
    bolt_spacing: float
    boss_diameter: float
    shaft_diameter: float
    shaft_flat_depth: float
    shaft_length: float

    @property
    def bolt_positions(self) -> tuple[tuple[float, float], ...]:
        """The four mounting holes, as (x, y) about the shaft."""
        half = self.bolt_spacing / 2
        return ((-half, -half), (half, -half), (-half, half), (half, half))


NEMA_17 = NemaStepperSpec(
    face_size=41.0,
    bolt_spacing=31.0,
    boss_diameter=22.0,
    shaft_diameter=5.0,
    shaft_flat_depth=0.5,
    shaft_length=20.0,
)
