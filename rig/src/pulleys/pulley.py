import math
from dataclasses import dataclass
from typing import cast

from build123d import (
    Circle,
    Line,
    Part,
    Pos,
    ThreePointArc,
    Vector,
    Wire,
    extrude,
    make_face,
)

from pulleys.belt_specs import GT2_2MM, TimingBeltSpec


def _polar(radius: float, angle: float) -> Vector:
    return Vector(radius * math.cos(angle), radius * math.sin(angle), 0.0)


@dataclass(frozen=True)
class ToothedBand:
    """The grooved band a belt wraps, and the numbers its groove is cut from."""

    belt: TimingBeltSpec
    teeth: int
    width: float

    @property
    def pitch_radius(self) -> float:
        """Radius the belt's pitch line wraps onto, one whose circumference is teeth * pitch."""
        return self.teeth * self.belt.pitch / (2 * math.pi)

    @property
    def tip_radius(self) -> float:
        """Radius of the flat tip between two grooves, the band's outermost surface."""
        return self.pitch_radius - self.belt.pitch_line_offset

    @property
    def _groove_mouth_radius(self) -> float:
        """Radius where the flanks give way to the root arc, the groove's opening."""
        return self.tip_radius - self.belt.flank_drop

    @property
    def _groove_center_radius(self) -> float:
        """Radius the root arc's own center sits at, so the arc meets both flanks."""
        mouth, half = self._groove_mouth_radius, self._groove_half_angle
        offset = mouth * math.sin(half)
        return mouth * math.cos(half) + math.sqrt(
            self.belt.groove_radius**2 - offset**2
        )

    @property
    def root_radius(self) -> float:
        """Radius of the groove's deepest point, the band's innermost surface."""
        return self._groove_center_radius - self.belt.groove_radius

    @property
    def _groove_half_angle(self) -> float:
        """Half a groove's opening, as the angle it turns through once wrapped."""
        return (self.belt.groove_mouth_width / 2) / self.pitch_radius

    @property
    def _flank_angle(self) -> float:
        """One flank's run, as the angle it turns through once wrapped."""
        return self.belt.flank_run / self.pitch_radius

    def profile(self) -> Wire:
        step = 2 * math.pi / self.teeth
        half, flank = self._groove_half_angle, self._flank_angle
        mouth, root, tip = self._groove_mouth_radius, self.root_radius, self.tip_radius

        edges = []
        for index in range(self.teeth):
            here = index * step
            mouth_in = _polar(mouth, here - half)
            deepest = _polar(root, here)
            mouth_out = _polar(mouth, here + half)
            tip_in = _polar(tip, here + half + flank)
            land_mid = _polar(tip, here + step / 2)
            tip_out = _polar(tip, here + step - half - flank)
            next_mouth_in = _polar(mouth, here + step - half)

            edges += [
                ThreePointArc(mouth_in, deepest, mouth_out),
                Line(mouth_out, tip_in),
                ThreePointArc(tip_in, land_mid, tip_out),
                Line(tip_out, next_mouth_in),
            ]
        return Wire(edges)

    def build(self) -> Part:
        return cast(Part, extrude(make_face(self.profile()), self.width))


@dataclass(frozen=True)
class Flange:
    """A rim on one side of the band, given by how far it stands over the tooth tips."""

    rim: float
    thickness: float

    def diameter(self, band: ToothedBand) -> float:
        """Outer diameter of the disc, the band's tips plus the rim on each side."""
        return 2 * (band.tip_radius + self.rim)


@dataclass(frozen=True)
class TimingPulley:
    """A solid pulley standing on its lower flange, grown upward along +Z.

    Attributes:
        band: the grooved band the belt wraps.
        flange: the rim on each side that keeps the belt from walking off.
    """

    band: ToothedBand
    flange: Flange

    @property
    def height(self) -> float:
        return self.band.width + 2 * self.flange.thickness

    def build(self) -> Part:
        disc = extrude(
            Circle(self.flange.diameter(self.band) / 2), self.flange.thickness
        )
        solid = disc
        solid += Pos(0.0, 0.0, self.flange.thickness) * self.band.build()
        solid += Pos(0.0, 0.0, self.flange.thickness + self.band.width) * disc
        return cast(Part, solid)


DRIVE_PULLEY = TimingPulley(
    band=ToothedBand(belt=GT2_2MM, teeth=60, width=7.0),
    flange=Flange(rim=2.0, thickness=1.5),
)


def build() -> Part:
    return DRIVE_PULLEY.build()
