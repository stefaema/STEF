from typing import cast

from build123d import (
    Align,
    Axis,
    Box,
    Part,
    Plane,
    Polygon,
    Pos,
    revolve,
)

from fasteners.screw_specs import SCREW_M3_COUNTERSUNK, ScrewSpec

HEAD_CLEARANCE = 0.2  # added to the head's diameter, so a sunk head drops in
CUT_OVERSHOOT = 0.5  # how far the cutter stands above the surface

SAMPLE_SLAB = (20.0, 20.0, 6.0)


class ScrewHole:
    """The hole a screw passes through, with its head either proud or sunk flush.

    The hole runs down from `at`, which sits on the surface the head lands on.
    """

    def __init__(
        self,
        at: tuple[float, float, float] = (0.0, 0.0, 0.0),
        spec: ScrewSpec = SCREW_M3_COUNTERSUNK,
        sink_head: bool = False,
    ) -> None:
        self.spec = spec
        self.sink_head = sink_head
        self.bore_radius = spec.thread.clearance_bore / 2
        self.head_radius = (spec.head_diameter + HEAD_CLEARANCE) / 2
        self.at = at

    @property
    def sunk_depth(self) -> float:
        """How far the head reaches below the surface, zero when it stays proud."""
        return self.spec.head_height if self.sink_head else 0.0

    def cutter(self, depth: float) -> Part:
        """Solid to subtract to leave the hole, `depth` measured down from the surface."""
        if depth <= self.sunk_depth:
            raise ValueError(
                f"depth {depth} leaves no bore under a head sunk {self.sunk_depth} deep"
            )

        if self.sink_head:
            # A funnel (a.k.a. countersink): head radius at the surface,
            # narrowing to bore radius over the head's height, then straight
            # down to `depth`.
            profile = Polygon(
                (0.0, CUT_OVERSHOOT),
                (self.head_radius, CUT_OVERSHOOT),
                (self.head_radius, 0.0),
                (self.bore_radius, -self.spec.head_height),
                (self.bore_radius, -depth),
                (0.0, -depth),
                align=None,
            )
        else:
            # A plain cylinder at bore radius, which the screw passes through
            # loose. The head lands on the surface, so nothing is opened for it.
            profile = Polygon(
                (0.0, CUT_OVERSHOOT),
                (self.bore_radius, CUT_OVERSHOOT),
                (self.bore_radius, -depth),
                (0.0, -depth),
                align=None,
            )
        hole = revolve((Plane.XZ * profile).face(), axis=Axis.Z)
        return cast(Part, Pos(*self.at) * hole)


def sample() -> dict[str, Part]:
    """One slab per head treatment, to check a sunk head really ends up below the surface."""
    length, width, height = SAMPLE_SLAB
    slab = Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return {
        name: cast(
            Part,
            slab
            - ScrewHole(at=(0.0, 0.0, height), sink_head=sunk).cutter(
                height + CUT_OVERSHOOT
            ),
        )
        for name, sunk in (("proud", False), ("sunk", True))
    }
