from dataclasses import dataclass, field, replace

from rollers.oring_specs import OringSpec
from shared.film_formats import FilmGeometricFormat


@dataclass(frozen=True)
class FilmRollerGauge:
    """A film gauge a roller serves: its track diameter, and how it contacts the film.

    Attributes:
        film_format_spec: the film format this gauge is designed for.
        track_diameter: the roller's track diameter, measured from the center of the
            film's contact band.
        contact: The specifics of how the roller's contact band is shaped.
            None if solid, OringSpec if it has a rubber O-ring.
        axial_clearance: how much extra space to leave on each side of the film's
            contact band, to avoid rubbing against the roller's edges.
        effective_format: the film format this gauge actually serves, after accounting
            for axial_clearance. Makes the film fit in the roller's contact band without
            rubbing against its edges.
    """

    film_format_spec: FilmGeometricFormat
    track_diameter: float
    contact: OringSpec | None = None
    axial_clearance: float = 0.2
    effective_format: FilmGeometricFormat = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effective_format",
            replace(
                self.film_format_spec,
                width=self.film_format_spec.width + 2 * self.axial_clearance,
                guide_side_margin=self.film_format_spec.guide_side_margin
                + self.axial_clearance,
                opposite_side_margin=self.film_format_spec.opposite_side_margin
                + self.axial_clearance,
            ),
        )
