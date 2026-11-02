from typing import cast

from build123d import Align, Box, Part, Pos

from mounts.side_panel import SidePanelFacing, as_part
from mounts.wago_222 import CHANNEL_WIDTH_5CABLE, Wago222Mount

SIDEWALL_THICKNESS = 2.0


class WagoPair:
    """Two Wago holders sharing one back, opening opposite ways along one axis.

    A single holder is closed at one end and loaded from the other. Put two of
    them back to back and the two closed ends coincide, so the pair is one piece
    with one spine, and each half is reached from its own side.
    """

    def __init__(
        self,
        at: tuple[float, float, float],
        channel_width: float = CHANNEL_WIDTH_5CABLE,
        facing: SidePanelFacing = SidePanelFacing.Y_POS,
        sidewall_thickness: float = SIDEWALL_THICKNESS,
    ) -> None:
        self.at = at
        self.channel_width = channel_width
        self.facing = facing
        self.sidewall_thickness = sidewall_thickness

    @property
    def span(self) -> float:
        """End to end along the opening axis, both channels plus the shared spine."""
        return 2 * Wago222Mount.CHANNEL_LENGTH + self.sidewall_thickness

    @property
    def width(self) -> float:
        """Width across the opening axis (the channel plus a sidewall on each side)."""
        return self.channel_width + 2 * self.sidewall_thickness

    @property
    def height(self) -> float:
        return Wago222Mount.CHANNEL_HEIGHT

    def _halves(self) -> list[Wago222Mount]:
        """The two holders. Each is moved back from the centre by half the spine.

        Moving both by half a wall makes their end walls share one slab. Otherwise
        one holder would cut into the other's channel.
        """
        east, north = self.facing.unit_vector
        back_off = self.sidewall_thickness / 2
        x, y, z = self.at
        return [
            Wago222Mount(
                at=(x + side * back_off * east, y + side * back_off * north, z),
                facing=direction,
                channel_width=self.channel_width,
                sidewall_thickness=self.sidewall_thickness,
            )
            for direction, side in (
                (self.facing, 1.0),
                (self.facing.opposite, -1.0),
            )
        ]

    def body(self) -> Part:
        halves = Part()
        for half in self._halves():
            halves += half.body()
        return cast(Part, halves)

    def sample(self, floor_thickness: float = 2.0) -> Part:
        body = self.body()
        bounds = body.bounding_box()
        floor = Pos(bounds.min.X, bounds.min.Y, bounds.min.Z - floor_thickness) * Box(
            bounds.size.X,
            bounds.size.Y,
            floor_thickness,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        return as_part(floor + body)


def sample() -> Part:
    return WagoPair(at=(0.0, 0.0, 0.0)).sample()
