from typing import cast

from build123d import (
    Align,
    Cone,
    Cylinder,
    Part,
    PolarLocations,
    Pos,
)

GRIP_DIAMETER = 21.8

BEARING_OD = 22.0
BEARING_WIDTH = 7.0

SHOULDER_WIDTH = 1.0
WALL_THICKNESS = 2.5
RELIEF_GAP = 0.3
RIM_CLEARANCE = 0.2
LEAD_IN = 0.5

RIB_COUNT = 6
RIB_RADIUS = 1.0

CUT_OVERSHOOT = 0.5

SAMPLE_BACKING = 1.5


class BearingSeat:
    def __init__(
        self,
        grip_diameter: float = GRIP_DIAMETER,
        bearing_od: float = BEARING_OD,
        bearing_width: float = BEARING_WIDTH,
        shoulder_width: float = SHOULDER_WIDTH,
    ) -> None:
        self.grip_radius = grip_diameter / 2
        self.relief_radius = bearing_od / 2 + RELIEF_GAP
        self.bore_radius = bearing_od / 2 - shoulder_width
        self.depth = bearing_width + RIM_CLEARANCE

    @property
    def boss_radius(self) -> float:
        return self.relief_radius + WALL_THICKNESS

    def cutter(self, bore_depth: float) -> Part:
        pocket = Cylinder(
            self.relief_radius,
            self.depth,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        ribs = PolarLocations(self.grip_radius + RIB_RADIUS, RIB_COUNT) * Cylinder(
            RIB_RADIUS, self.depth, align=(Align.CENTER, Align.CENTER, Align.MIN)
        )
        mouth = Pos(0.0, 0.0, self.depth - LEAD_IN) * Cone(
            self.grip_radius,
            self.relief_radius + LEAD_IN,
            LEAD_IN,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        bore = Pos(0.0, 0.0, -bore_depth) * Cylinder(
            self.bore_radius,
            bore_depth,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        return cast(Part, (pocket - ribs) + mouth + bore)


def sample() -> Part:
    seat = BearingSeat()
    puck = Cylinder(
        seat.boss_radius,
        SAMPLE_BACKING + seat.depth,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    return cast(
        Part,
        puck
        - Pos(0.0, 0.0, SAMPLE_BACKING) * seat.cutter(SAMPLE_BACKING + CUT_OVERSHOOT),
    )
