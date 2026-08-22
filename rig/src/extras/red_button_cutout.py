from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos

CUT_OVERSHOOT = 0.5

BUTTON_DIAMETER = 24.0

SAMPLE_MARGIN = 8.5
SAMPLE_THICKNESS = 3.0


class RedButtonCutout:
    def __init__(
        self,
        at: tuple[float, float, float],
        thickness: float,
        diameter: float = BUTTON_DIAMETER,
    ) -> None:
        self.at = at
        self.thickness = thickness
        self.radius = diameter / 2

    def cutout(self) -> Part:
        x, y, z = self.at
        return Pos(x, y, z - CUT_OVERSHOOT) * Cylinder(
            self.radius,
            self.thickness + 2 * CUT_OVERSHOOT,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )


def sample() -> Part:
    button = RedButtonCutout(at=(0.0, 0.0, 0.0), thickness=SAMPLE_THICKNESS)
    span = 2 * (button.radius + SAMPLE_MARGIN)
    plate = Box(
        span,
        span,
        SAMPLE_THICKNESS,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    return cast(Part, plate - button.cutout())
