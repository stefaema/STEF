from abc import ABC, abstractmethod

from build123d import Part


class AxialCore(ABC):
    """Joint between an axially-defined body (e.g. a roller) and what it mounts on (such as a bearing or shaft).

    Attributes:
        length: the core's axial length, end face to end face.
    """

    length: float

    @property
    @abstractmethod
    def end_depth(self) -> float:
        """How far the core's features reach in from an end face. Whatever closes the body's ends must be at least this thick."""

    @abstractmethod
    def check_radius(self, radius: float) -> None:
        """Raise if a body of `radius` leaves the core's features without enough material around them."""

    @abstractmethod
    def cutters(self) -> Part:
        """Solid to subtract from the body to leave the core's features."""
