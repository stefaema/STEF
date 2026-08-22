from enum import Enum
from typing import NamedTuple, cast

from bearings.core import BearingCore
from build123d import (
    Axis,
    Edge,
    Line,
    Part,
    Plane,
    SagittaArc,
    make_face,
    revolve,
)

TRACK_16_DIAMETER = 30.0
TRACK_35_DIAMETER = 38.0

RING_16_CENTRE = 7.0
RING_35_CENTRE = 16.5
RING_WIDTH = 2.0
RING_DEPTH = 1.0
RING_FOOTPRINT = RING_WIDTH + 2 * RING_DEPTH

GUIDE_LIP = 2.0
GUIDE_RISE = RING_DEPTH + GUIDE_LIP
RIM_WIDTH = 1.0

TRACK_16_HOLLOW = 0.5
STEP_HOLLOW = 0.15


class Point(NamedTuple):
    radius: float
    axial: float


class Segment(NamedTuple):
    start: Point
    end: Point
    hollow: float = 0.0

    def edge(self) -> Edge:
        if self.hollow:
            return SagittaArc(self.start, self.end, self.hollow)
        return Line(self.start, self.end)

    def mirrored(self) -> "Segment":
        return Segment(
            Point(self.end.radius, -self.end.axial),
            Point(self.start.radius, -self.start.axial),
            self.hollow,
        )


class Outline:
    def __init__(self, start: Point) -> None:
        self.at = start
        self.segments: list[Segment] = []

    def _to(self, radius: float, axial: float, hollow: float = 0.0) -> "Outline":
        end = Point(radius, axial)
        if end != self.at:
            self.segments.append(Segment(self.at, end, hollow))
            self.at = end
        return self

    def track_to(self, axial: float) -> "Outline":
        return self._to(self.at.radius, axial)

    def ring(self, centre: float, offset: float) -> "Outline":
        track = self.at.radius
        self.track_to(centre - RING_FOOTPRINT / 2)
        self._to(track + offset, centre - RING_WIDTH / 2)
        self._to(track + offset, centre + RING_WIDTH / 2)
        return self._to(track, centre + RING_FOOTPRINT / 2)

    def guide(self) -> "Outline":
        return self._to(self.at.radius + GUIDE_RISE, self.at.axial + GUIDE_RISE)

    def step_to(self, radius: float, axial: float) -> "Outline":
        return self._to(radius, axial, STEP_HOLLOW)

    def rim(self) -> "Outline":
        return self.track_to(self.at.axial + RIM_WIDTH)


class RingSign(Enum):
    GROOVE = "groove"
    BAND = "band"

    @property
    def ring_offset(self) -> float:
        return -RING_DEPTH if self is RingSign.GROOVE else RING_DEPTH


class IdlerRoller:
    def __init__(
        self,
        sign: RingSign = RingSign.GROOVE,
        ring_16_centre: float = RING_16_CENTRE,
        ring_35_centre: float = RING_35_CENTRE,
    ) -> None:
        self.sign = sign
        self.ring_16_centre = ring_16_centre
        self.ring_35_centre = ring_35_centre
        guide_16_top = ring_16_centre + RING_FOOTPRINT / 2 + GUIDE_RISE
        ring_35_foot = ring_35_centre - RING_FOOTPRINT / 2
        if guide_16_top > ring_35_foot:
            raise ValueError(
                f"16mm guide tops out at {guide_16_top}, past the 35mm ring "
                f"footprint at {ring_35_foot}"
            )
        self.core = BearingCore(length=self.length, at=(0.0, 0.0, -self.half_length))
        if self.core.min_shell_diameter > self.waist_diameter:
            raise ValueError(
                f"core {self.core.min_shell_diameter} pokes through "
                f"the waist {self.waist_diameter}"
            )

    @property
    def half_length(self) -> float:
        return self._profile()[-1].end.axial

    @property
    def length(self) -> float:
        return 2 * self.half_length

    @property
    def waist_diameter(self) -> float:
        return 2 * min(
            min(segment.start.radius, segment.end.radius) - segment.hollow
            for segment in self._profile()
        )

    def _half_profile(self) -> list[Segment]:
        track_16 = TRACK_16_DIAMETER / 2
        track_35 = TRACK_35_DIAMETER / 2
        offset = self.sign.ring_offset

        outline = Outline(Point(track_16, self.ring_16_centre - RING_FOOTPRINT / 2))
        outline.ring(self.ring_16_centre, offset).guide()
        outline.step_to(track_35, self.ring_35_centre - RING_FOOTPRINT / 2)
        outline.ring(self.ring_35_centre, offset).guide().rim()
        return outline.segments

    def _profile(self) -> list[Segment]:
        half = self._half_profile()
        inner = half[0].start
        centre = Segment(Point(inner.radius, -inner.axial), inner, TRACK_16_HOLLOW)
        return [segment.mirrored() for segment in reversed(half)] + [centre] + half

    def barrel(self) -> Part:
        profile = self._profile()
        first, last = profile[0].start, profile[-1].end
        edges = [segment.edge() for segment in profile]
        edges.append(Line(last, Point(0.0, last.axial)))
        edges.append(Line(Point(0.0, last.axial), Point(0.0, first.axial)))
        edges.append(Line(Point(0.0, first.axial), first))
        face = Plane.XZ * make_face(edges)
        return cast(Part, revolve(face.faces(), Axis.Z))

    def build(self) -> Part:
        return cast(Part, self.barrel() - self.core.cutters())


def build() -> dict[str, Part]:
    return {sign.value: IdlerRoller(sign=sign).build() for sign in RingSign}
