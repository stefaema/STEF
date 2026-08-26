from typing import cast

from build123d import (
    Align,
    Axis,
    Cylinder,
    Part,
    Plane,
    PolarLocations,
    Polygon,
    Pos,
    revolve,
)

from bearings.bearing_specs import BEARING_608, RadialBearingSpec

# press fit via ribs, instead of against the whole seat wall
RIB_COUNT = 6
RIB_RADIUS = 1.0
RIB_INTERFERENCE = 0.1  # how far the ribs pinch inside the bearing OD, radially

# pocket dimensions
RACE_SHOULDER_WIDTH = (
    1.0  # Isolates the bearing's inner race from the surrounding material
)
MINIMUM_WALL_THICKNESS = 2.5  # to ensure strong structure

# How much clearance to add to the pocket diameter against the bearing OD
SEAT_CLEARANCE = 0.3  # Radial
RIM_CLEARANCE = 0.2  # Axial
LEAD_IN = 0.5  # Mouth of the chamfered funnel-like pocket profile

# boolean-cut robustness
CUT_OVERSHOOT = 0.5

# sample-only
SAMPLE_BACKING = 1.5


class BearingSeat:
    """Pocket geometry that press-fits a radial bearing using ribs around the wall it sits against."""

    def __init__(
        self,
        bearing: RadialBearingSpec = BEARING_608,
        race_shoulder_width: float = RACE_SHOULDER_WIDTH,
    ) -> None:
        self.interference_radius = bearing.od / 2 - RIB_INTERFERENCE
        self.seat_radius = bearing.od / 2 + SEAT_CLEARANCE
        self.race_clearance_radius = bearing.od / 2 - race_shoulder_width
        self.depth = bearing.width + RIM_CLEARANCE
        self.minimum_wall_thickness = MINIMUM_WALL_THICKNESS

    @property
    def boss_radius(self) -> float:
        """Minimum solid radius needed to enclose the pocket and its wall."""
        return self.seat_radius + self.minimum_wall_thickness

    def check_radius(self, radius: float) -> None:
        """Raise if `radius` would leave the seat's wall thinner than minimum_wall_thickness."""
        if radius < self.boss_radius:
            raise ValueError(
                f"radius {radius} is below boss_radius {self.boss_radius}, "
                f"wall would be thinner than minimum_wall_thickness {self.minimum_wall_thickness}"
            )

    def cutter(self, race_clearance_depth: float) -> Part:
        """Solid to substract from other piece to leave a bearing seat.

        `race_clearance_depth` is how far the clearance space below the shoulder
        ledge extends, so the bearing's inner race and whatever spins with it
        don't rub against the surrounding material."""

        # main holes: bearing pocket over the race clearance, expressed as a stepped profile
        pocket_and_bore = Polygon(
            (0.0, -race_clearance_depth),
            (self.race_clearance_radius, -race_clearance_depth),
            (self.race_clearance_radius, 0.0),
            (self.seat_radius, 0.0),
            (self.seat_radius, self.depth),
            (0.0, self.depth),
        )

        # funnel-shaped lead-in at the pocket's mouth, eases the bearing into place.
        # starts at interference_radius, so it reaches far enough in
        # to cover the rib notches instead of leaving them exposed
        mouth_profile = Polygon(
            (0.0, self.depth - LEAD_IN),
            (self.interference_radius, self.depth - LEAD_IN),
            (self.seat_radius + LEAD_IN, self.depth),
            (0.0, self.depth),
        )

        # sweep both profiles into solids
        body = revolve((Plane.XZ * pocket_and_bore).face(), axis=Axis.Z)
        mouth = revolve((Plane.XZ * mouth_profile).face(), axis=Axis.Z)
        ribs = PolarLocations(
            self.interference_radius + RIB_RADIUS, RIB_COUNT
        ) * Cylinder(
            RIB_RADIUS, self.depth, align=(Align.CENTER, Align.CENTER, Align.MIN)
        )
        return cast(Part, (body - ribs) + mouth)


def sample() -> Part:
    """Sample part that demonstrates the bearing seat geometry. Used for testing and visualization."""
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
