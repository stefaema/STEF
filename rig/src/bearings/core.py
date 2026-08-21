from typing import cast

from build123d import (
    Align,
    Cylinder,
    Part,
    Pos,
    Rot,
)

from bearings.seat import BearingSeat

SAMPLE_LENGTH = 35.2


class BearingCore:
    def __init__(
        self,
        length: float,
        at: tuple[float, float, float] = (0.0, 0.0, 0.0),
        seat: BearingSeat | None = None,
    ) -> None:
        self.seat = seat or BearingSeat()
        if length < 2 * self.seat.depth:
            raise ValueError(
                f"length {length} leaves no wall between two {self.seat.depth} seats"
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
        return Pos(self.at) * Cylinder(
            self.seat.boss_radius,
            self.length,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )

    def cutters(self) -> Part:
        lower_shoulder, upper_shoulder = self.shoulder_heights
        lower = (
            Pos(0.0, 0.0, lower_shoulder)
            * Rot(180.0, 0.0, 0.0)
            * self.seat.cutter(self.length)
        )
        upper = Pos(0.0, 0.0, upper_shoulder) * self.seat.cutter(self.length)
        return cast(Part, Pos(self.at) * (lower + upper))

    def build(self) -> Part:
        return cast(Part, self.body() - self.cutters())


def sample() -> Part:
    return BearingCore(length=SAMPLE_LENGTH).build()
