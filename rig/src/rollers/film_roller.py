from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from bearings.core import BearingCore
from build123d import (
    Align,
    Axis,
    Cone,
    Cylinder,
    Edge,
    Line,
    Part,
    Plane,
    PolarLocations,
    Pos,
    Rot,
    SagittaArc,
    Wire,
    make_face,
    revolve,
)

from rollers.gauges import FilmRollerGauge

OUTERMOST_FLANGE_WIDTH = 5.0  # floored by seat_depth, see _flange_width
INNER_FLANGE_WIDTH_RATIO = 0.12  # of the gauge's own film width
LIMIT_FLANGE_MARGIN = 2.0  # above track radius
WAIST_SAGITTA_RATIO = 0.015  # of the narrower gauge's track diameter
BAND_PROTRUSION_DEPTH = 1.0  # above bare track radius
JOINT_RIB_COUNT = 6
JOINT_RIB_RADIUS = 1.5
JOINT_RIB_INTERFERENCE = 0.4  # radial protrusion of each rib
JOINT_MALE_UNDERSIZE = (
    0.1  # how much smaller than the female wall the male is, see _male_plug
)
JOINT_LEAD_IN = (
    0.8  # height of the funnel easing the male into the ribs at the relief shoulder
)


# ── The profile, as regions rather than traced edges ────────────────────────


@dataclass(frozen=True)
class RollerPolarRegion:
    """One disc-shaped feature of the profile: a single radius over a z range."""

    radius: float
    z_range: tuple[float, float]

    def __post_init__(self) -> None:
        if self.z_range[0] > self.z_range[1]:
            raise ValueError(f"z_range {self.z_range} is not ordered low to high")

    @property
    def diameter(self) -> float:
        return 2 * self.radius

    @property
    def z_center(self) -> float:
        return sum(self.z_range) / 2

    @property
    def z_width(self) -> float:
        return self.z_range[1] - self.z_range[0]

    def cylinder(self) -> Part:
        """This region, extruded into a solid disc."""
        return cast(
            Part,
            Pos(0.0, 0.0, self.z_range[0])
            * Cylinder(
                self.radius, self.z_width, align=(Align.CENTER, Align.CENTER, Align.MIN)
            ),
        )


@dataclass(frozen=True)
class GaugeProfile:
    """One gauge's regions: what limits the film's play, what it rides on, and what it must never touch.

    Attributes:
        gauge: the gauge these regions were built for.
        limit_flanges: (opposite, guide) discs stopping the film's axial drift.
        contact_bands: (opposite, guide) discs the film's margin actually rides on.
        exclusion_zone: the film's own frame, at the contact bands' radius: no
            narrower gauge's profile may reach this far out while it overlaps
            this gauge's frame.
    """

    gauge: FilmRollerGauge
    limit_flanges: tuple[RollerPolarRegion, RollerPolarRegion]
    contact_bands: tuple[RollerPolarRegion, RollerPolarRegion]
    exclusion_zone: RollerPolarRegion


def _flange_radius(gauge: FilmRollerGauge) -> float:
    return gauge.track_diameter / 2 + LIMIT_FLANGE_MARGIN


def _flange_width(
    gauge: FilmRollerGauge, is_outermost: bool, seat_depth: float
) -> float:
    """How far a gauge's limit flange extends in z, its flat land beyond the film edge."""
    if is_outermost:
        return max(OUTERMOST_FLANGE_WIDTH, seat_depth)
    return gauge.effective_format.width * INNER_FLANGE_WIDTH_RATIO


def _waist_sagitta(gauge: FilmRollerGauge) -> float:
    return gauge.track_diameter * WAIST_SAGITTA_RATIO


def _gauge_profile(
    gauge: FilmRollerGauge, is_outermost: bool, seat_depth: float
) -> GaugeProfile:
    """Build gauge's regions: a limit flange and a contact band on each side, plus its exclusion zone."""
    fmt = gauge.effective_format
    track_radius = gauge.track_diameter / 2
    flange_radius = _flange_radius(gauge)
    flange_width = _flange_width(gauge, is_outermost, seat_depth)

    # Make use of the fact that the roller is symmetric about z=0, so we can build one side and mirror it.
    def side(sign: float) -> tuple[RollerPolarRegion, RollerPolarRegion]:
        edge_z = sign * fmt.width / 2
        margin_band = fmt.guide_side_band if sign > 0 else fmt.opposite_side_band
        if margin_band is None:
            inner_z, band_radius = edge_z, track_radius
        else:
            inner_z = margin_band[0]
            band_radius = min(track_radius + BAND_PROTRUSION_DEPTH, flange_radius)
        band = RollerPolarRegion(
            band_radius, (min(edge_z, inner_z), max(edge_z, inner_z))
        )
        flange_end = edge_z + sign * flange_width
        flange = RollerPolarRegion(
            flange_radius, (min(edge_z, flange_end), max(edge_z, flange_end))
        )
        return band, flange

    opposite_band, opposite_flange = side(-1.0)
    guide_band, guide_flange = side(1.0)
    exclusion_zone = RollerPolarRegion(
        max(opposite_band.radius, guide_band.radius),
        (fmt.opposite_side_start, fmt.guide_side_start),
    )
    return GaugeProfile(
        gauge=gauge,
        limit_flanges=(opposite_flange, guide_flange),
        contact_bands=(opposite_band, guide_band),
        exclusion_zone=exclusion_zone,
    )


def _near(region: RollerPolarRegion, sign: float) -> tuple[float, float]:
    """region's point closest to the axis (z=0), on the side sign selects."""
    return (region.radius, region.z_range[1] if sign < 0 else region.z_range[0])


def _far(region: RollerPolarRegion, sign: float) -> tuple[float, float]:
    """region's point farthest from the axis (z=0), on the side sign selects."""
    return (region.radius, region.z_range[0] if sign < 0 else region.z_range[1])


def _validated(gauges: Sequence[FilmRollerGauge]) -> list[FilmRollerGauge]:
    """Sort narrow to wide, or raise if two gauges share a film width."""
    if not gauges:
        raise ValueError("a roller needs at least one gauge")
    ordered = sorted(gauges, key=lambda gauge: gauge.effective_format.width)
    widths = [gauge.effective_format.width for gauge in ordered]
    if len(set(widths)) != len(widths):
        raise ValueError("gauges must have distinct film widths")
    return ordered


def _validate_profiles(profiles: Sequence[GaugeProfile]) -> None:
    """Raise if a narrower gauge's flange fouls a wider gauge's track or film."""
    for narrower, wider in zip(profiles, profiles[1:]):
        flange_radius = narrower.limit_flanges[1].radius
        track_radius = wider.gauge.track_diameter / 2
        if flange_radius > track_radius:
            raise ValueError(
                f"gauge at track diameter {narrower.gauge.track_diameter} has a "
                f"limiting flange reaching radius {flange_radius}, past the "
                f"track radius {track_radius} the wider gauge's film rides at"
            )
    for index, inner in enumerate(profiles):
        inner_radius = inner.limit_flanges[1].radius
        for outer in profiles[index + 1 :]:
            if inner_radius >= outer.exclusion_zone.radius:
                raise ValueError(
                    f"gauge at track diameter {inner.gauge.track_diameter} reaches "
                    f"radius {inner_radius}, inside the film path of the gauge at "
                    f"track diameter {outer.gauge.track_diameter} "
                    f"(exclusion zone radius {outer.exclusion_zone.radius})"
                )


def total_length(gauges: Sequence[FilmRollerGauge], seat_depth: float) -> float:
    """The roller's own total axial length, from one outermost flange's outer face to the other's."""
    ordered = _validated(gauges)
    widest = ordered[-1]
    contact = widest.effective_format.width / 2
    flange_width = _flange_width(widest, True, seat_depth)
    return 2 * (contact + flange_width)


def _side_silhouette(profiles: Sequence[GaugeProfile], sign: float) -> list[Edge]:
    """One side's outer silhouette, narrow to wide, adding arcs whenever it's needed.

    Arcs are drawn to connect a contact band of a wider gauge to a limit flange of a thinner one.
    """
    edges: list[Edge] = []
    for index, profile in enumerate(profiles):
        band = profile.contact_bands[1] if sign > 0 else profile.contact_bands[0]
        flange = profile.limit_flanges[1] if sign > 0 else profile.limit_flanges[0]
        points = [
            _near(band, sign),
            _far(band, sign),
            _near(flange, sign),
            _far(flange, sign),
        ]
        for start, end in zip(points, points[1:]):
            if start != end:
                edges.append(Line(start, end))
        if index < len(profiles) - 1:
            next_profile = profiles[index + 1]
            next_band = (
                next_profile.contact_bands[1]
                if sign > 0
                else next_profile.contact_bands[0]
            )
            here, there = _far(flange, sign), _near(next_band, sign)
            sagitta = _waist_sagitta(profile.gauge)
            # SagittaArc's bulge direction depends on point order
            edges.append(
                SagittaArc(here, there, sagitta)
                if sign > 0
                else SagittaArc(there, here, sagitta)
            )
    return edges


# ── The roller itself ────────────────────────────────────────────────────────


@dataclass
class FilmRoller:
    """Factory for a roller serving one or more film gauges.

    core.length must equal this roller's own total_length; raises otherwise.
    """

    gauges: Sequence[FilmRollerGauge]
    core: BearingCore

    def __post_init__(self) -> None:
        self.gauges = _validated(self.gauges)
        self.profiles = [
            _gauge_profile(gauge, index == len(self.gauges) - 1, self.core.seat.depth)
            for index, gauge in enumerate(self.gauges)
        ]
        _validate_profiles(self.profiles)
        self.core.seat.check_radius(_flange_radius(self.gauges[-1]))
        expected = total_length(self.gauges, self.core.seat.depth)
        if self.core.length != expected:
            raise ValueError(
                f"core.length {self.core.length} doesn't match this roller's "
                f"total length {expected}"
            )

    def _half_length(self) -> float:
        return total_length(self.gauges, self.core.seat.depth) / 2

    def _body(self) -> Part:
        """Revolve the whole roller's limiting-stage profile in one pass."""
        half_length = self._half_length()
        widest = self.profiles[-1]
        innermost = self.profiles[0]

        opposite_radial_line = Line(
            (0.0, -half_length), _far(widest.limit_flanges[0], -1.0)
        )

        opposite_axial_silhouette = reversed(_side_silhouette(self.profiles, -1.0))

        # Connect the innermost contact bands with a sagitta arc, so the roller's own body doesn't touch the film.
        waist_arc = SagittaArc(
            _near(innermost.contact_bands[0], -1.0),
            _near(innermost.contact_bands[1], 1.0),
            _waist_sagitta(innermost.gauge),
        )

        guide_axial_silhouette = _side_silhouette(self.profiles, 1.0)

        guide_radial_line = Line(_far(widest.limit_flanges[1], 1.0), (0.0, half_length))

        # Close the profile parallel to the axis (actually, the axis itself) so revolve() can make a solid.
        axis_closure = Line((0.0, half_length), (0.0, -half_length))

        edges: list[Edge] = [
            opposite_radial_line,
            *opposite_axial_silhouette,
            waist_arc,
            *guide_axial_silhouette,
            guide_radial_line,
            axis_closure,
        ]
        wire = Wire(edges)
        face = make_face(wire)
        return revolve((Plane.XZ * face).face(), axis=Axis.Z)

    def build_one_piece(self) -> Part:
        return cast(Part, self._body() - self.core.cutters())

    def _joint_regions(
        self,
    ) -> tuple[float, float, float, RollerPolarRegion, RollerPolarRegion]:
        """(bottom_shoulder, contact_z, band_radius, upper, band) shared by the male and female sides of the split."""
        half_length = self._half_length()
        bottom_shoulder = -(half_length - self.core.seat.depth)
        upper_radius = _flange_radius(self.gauges[-1])
        opposite_band = self.profiles[0].contact_bands[0]
        band_radius = opposite_band.radius
        split_z = _near(opposite_band, -1.0)[1]
        contact_z = _far(opposite_band, -1.0)[1]
        upper = RollerPolarRegion(upper_radius, (split_z, half_length))
        band = RollerPolarRegion(band_radius, (contact_z, split_z))
        return (bottom_shoulder, contact_z, band_radius, upper, band)

    def _female_cut(self) -> Part:
        """The tool subtracted from the whole roller to bore the female socket."""
        bottom_shoulder, contact_z, band_radius, upper, band = self._joint_regions()
        press_fit_height = contact_z - bottom_shoulder
        socket = Pos(0.0, 0.0, bottom_shoulder) * Cylinder(
            band_radius, press_fit_height, align=(Align.CENTER, Align.CENTER, Align.MIN)
        )
        interference_radius = band_radius - JOINT_RIB_INTERFERENCE
        straight_height = press_fit_height - JOINT_LEAD_IN
        rib_tool = Pos(0.0, 0.0, bottom_shoulder) * Cylinder(
            JOINT_RIB_RADIUS,
            straight_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        ) + Pos(0.0, 0.0, bottom_shoulder + straight_height) * Cone(
            JOINT_RIB_RADIUS,
            JOINT_RIB_RADIUS - JOINT_RIB_INTERFERENCE,
            JOINT_LEAD_IN,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        ribs = (
            PolarLocations(interference_radius + JOINT_RIB_RADIUS, JOINT_RIB_COUNT)
            * rib_tool
        )
        return cast(Part, upper.cylinder() + band.cylinder() + (socket - ribs))

    def _male_plug(self) -> Part:
        """The tool intersected with the whole roller to shape the male insert."""
        bottom_shoulder, contact_z, band_radius, upper, band = self._joint_regions()
        straight_height = (contact_z - bottom_shoulder) - JOINT_LEAD_IN
        plug = Pos(0.0, 0.0, bottom_shoulder) * Cylinder(
            band_radius - JOINT_MALE_UNDERSIZE,
            straight_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        ) + Pos(0.0, 0.0, bottom_shoulder + straight_height) * Cone(
            band_radius - JOINT_MALE_UNDERSIZE,
            band_radius,
            JOINT_LEAD_IN,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        return cast(Part, upper.cylinder() + band.cylinder() + plug)

    def build_two_piece(self) -> tuple[Part, Part]:
        """Split the whole roller into a female and a male piece, joined by a ribbed press fit."""
        if len(self.gauges) < 2:
            raise ValueError(
                "a single-gauge roller has no narrower gauge's band to carve the "
                "joint's press fit out of, so build_two_piece isn't supported yet; "
                "use build_one_piece instead"
            )
        whole = self.build_one_piece()
        female = cast(Part, whole - self._female_cut())
        male = cast(Part, Rot(180.0, 0.0, 0.0) * (whole & self._male_plug()))
        return (female, male)
