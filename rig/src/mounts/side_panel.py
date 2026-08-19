from abc import ABC, abstractmethod
from enum import Enum
from math import atan2, degrees
from typing import Self

from build123d import Align, Box, Part, Plane, Pos, Rot, Vector, mirror
from build123d.topology import Shape

CUT_OVERSHOOT = 0.5
SAMPLE_CEILING = 2.0


def as_part(shape: Shape) -> Part:
    return Part(shape.solids())


class SidePanelFacing(Enum):
    """
    The direction a side panel mount faces, as a unit vector in the XY plane.
    """

    X_POS = (1.0, 0.0)
    Y_POS = (0.0, 1.0)
    X_NEG = (-1.0, 0.0)
    Y_NEG = (0.0, -1.0)

    @property
    def unit_vector(self) -> tuple[float, float]:
        """Return the unit vector for this facing."""
        return self.value

    @property
    def z_rotation(self) -> float:
        """Return the Z-axis rotation (yaw) for this facing, in degrees."""
        east, north = self.value
        return degrees(atan2(north, east)) % 360.0

    def is_perpendicular_to(self, other: "SidePanelFacing") -> bool:
        """Return True if this facing is perpendicular to the other facing."""
        east, north = self.value
        other_east, other_north = other.value
        return east * other_east + north * other_north == 0.0


class SidePanelMount(ABC):
    CHANNEL_LENGTH: float
    CHANNEL_WIDTH: float
    CHANNEL_HEIGHT: float
    CLAMP_POINTS: tuple[tuple[float, float], ...]
    STEP_SPANS: tuple[tuple[float, float, float], ...]

    def __init__(
        self,
        at: tuple[float, float, float],
        facing: SidePanelFacing,
        panel_thickness: float,
        sidewall_thickness: float = 2.0,
    ) -> None:
        """Initialize a side panel mount."""
        self.panel_thickness = panel_thickness
        self.sidewall_thickness = sidewall_thickness
        self._placement = Pos(*at) * Rot(0.0, 0.0, facing.z_rotation)

    @classmethod
    def bank(
        cls,
        at: tuple[float, float, float],
        facing: SidePanelFacing,
        panel_thickness: float,
        count: int,
        growing_toward: SidePanelFacing,
        sidewall_thickness: float = 2.0,
    ) -> list[Self]:
        """
        Return a list of side panel mounts arranged in a bank,
        starting at the given position and growing in the given direction.
        """
        if count < 1:
            raise ValueError(f"count must be at least 1, got {count}")
        if not facing.is_perpendicular_to(growing_toward):
            raise ValueError(
                f"growing_toward {growing_toward.name} must be perpendicular to "
                f"facing {facing.name}"
            )

        pitch = cls.CHANNEL_WIDTH + sidewall_thickness
        east, north = growing_toward.unit_vector
        x, y, z = at
        return [
            cls(
                at=(x + n * pitch * east, y + n * pitch * north, z),
                facing=facing,
                panel_thickness=panel_thickness,
                sidewall_thickness=sidewall_thickness,
            )
            for n in range(count)
        ]

    @abstractmethod
    def _retention_ribs(self) -> Part:
        """
        Return the ribs that narrow the channel to grip the connector,
        stopping it sliding along its axis or shifting sideways.
        """

    def _locating_features(self) -> Part:
        """
        Return everything that holds the connector in the channel.
        """
        return as_part(self._retention_ribs() + self._levelling_steps())

    def _levelling_steps(self) -> Part:
        """
        Return the steps that carry the parts of the connector's underside
        sitting higher than its lowest face, so it seats without rocking.
        """
        steps = Part()
        for start, length, height in self.STEP_SPANS:
            steps += Pos(start, 0.0, 0.0) * Box(
                length,
                self.CHANNEL_WIDTH,
                height,
                align=(Align.MIN, Align.CENTER, Align.MIN),
            )
        return steps

    @abstractmethod
    def _cutout_solid(self) -> Part:
        """
        Return the cutout solid of the mount,
        which is subtracted from the panel to create the actual cutout.
        """

    def body(self) -> Part:
        """
        Return the solid body of the mount,
        including sidewalls and locating features, but not the cutout.
        """
        return self._placement * as_part(self._sidewalls() + self._locating_features())

    def cutout(self) -> Part:
        """
        Return the cutout solid of the mount,
        which is subtracted from the panel.
        """
        return self._placement * self._cutout_solid()

    def clamp_points(self) -> list[Vector]:
        """
        Return the points where something above, such as a lid, must press
        down to trap the connector against the mount.
        """
        return [
            (self._placement * Pos(x, 0.0, height)).position
            for x, height in self.CLAMP_POINTS
        ]

    def sample(self, floor_thickness: float = 2.0) -> Part:
        """
        Return a sample solid of the mount,
        including the panel and floor, for visualization and testing purposes.
        """
        span = self.CHANNEL_WIDTH + 2 * self.sidewall_thickness
        base = Pos(-self.panel_thickness, -span / 2, -floor_thickness)

        floor = base * Box(
            self.panel_thickness + self.CHANNEL_LENGTH,
            span,
            floor_thickness,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        cutout = self._cutout_solid()
        panel_height = max(
            self.CHANNEL_HEIGHT,
            cutout.bounding_box().max.Z + SAMPLE_CEILING,
        )
        panel = base * Box(
            self.panel_thickness,
            span,
            floor_thickness + panel_height,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        body = self._sidewalls() + self._locating_features()
        return as_part(floor + panel + body - cutout)

    def _sidewalls(self) -> Part:
        """
        Return the sidewalls of the mount,
        which hold the connector in place along with the locating features.
        """
        wall = Pos(0.0, self.CHANNEL_WIDTH / 2, 0.0) * Box(
            self.CHANNEL_LENGTH,
            self.sidewall_thickness,
            self.CHANNEL_HEIGHT,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        return as_part(wall + mirror(wall, Plane.XZ))
