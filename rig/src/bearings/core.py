from enum import Enum
from typing import cast

from build123d import (
    Align,
    Cylinder,
    Part,
    Pos,
    Rot,
)

from bearings.seat import BearingSeat

SAMPLE_LENGTH = 32


class BearingPlacement(Enum):
    """Which end(s) of a BearingCore get a bearing seat cut into them."""

    BOTH_SIDES = "both_sides"
    TOP_SIDE = "top_side"
    BOTTOM_SIDE = "bottom_side"


class BearingCore:
    """A cylinder with a bearing seat cut into one or both ends."""

    def __init__(
        self,
        length: float,
        seat: BearingSeat,
        bearing_at: BearingPlacement = BearingPlacement.BOTH_SIDES,
        at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        self.seat = seat
        self.bearing_at = bearing_at
        seat_count = 2 if bearing_at is BearingPlacement.BOTH_SIDES else 1
        if length < seat_count * self.seat.depth:
            raise ValueError(
                f"length {length} leaves no wall for {seat_count} "
                f"{self.seat.depth}-deep seat(s)"
            )
        self.length = length
        self.at = at

    @property
    def min_shell_diameter(self) -> float:
        return 2 * self.seat.boss_radius

    @property
    def shoulder_heights(self) -> tuple[float, float]:
        return (self.seat.depth, self.length - self.seat.depth)

    def body(self) -> Part:
        """The cylinder that will be cut to make the bearing seat(s)."""
        return Pos(self.at) * Cylinder(
            self.seat.boss_radius,
            self.length,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )

    def cutters(self) -> Part:
        """The cutout(s) that will be subtracted from the body to make the bearing seat(s)."""
        lower_shoulder, upper_shoulder = self.shoulder_heights
        lower = (
            Pos(0.0, 0.0, lower_shoulder)
            * Rot(180.0, 0.0, 0.0)
            * self.seat.cutter(self.length)
        )
        upper = Pos(0.0, 0.0, upper_shoulder) * self.seat.cutter(self.length)
        cutout = {
            BearingPlacement.BOTH_SIDES: lower + upper,
            BearingPlacement.BOTTOM_SIDE: lower,
            BearingPlacement.TOP_SIDE: upper,
        }[self.bearing_at]
        return cast(Part, Pos(self.at) * cutout)

    def build(self) -> Part:
        """The cylinder with the bearing seat(s) cut into it."""
        return cast(Part, self.body() - self.cutters())


def sample() -> Part:
    return BearingCore(length=SAMPLE_LENGTH, seat=BearingSeat()).build()
