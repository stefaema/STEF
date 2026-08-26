"""Physical properties of motion-picture film, geometric dimensions in millimeters."""

from dataclasses import dataclass
from enum import Enum, auto


class FilmBase(Enum):
    ACETATE = auto()
    POLYESTER = auto()
    NITRATE = auto()


@dataclass(frozen=True)
class FilmMaterialProfile:
    base: FilmBase
    is_negative: bool


@dataclass(frozen=True)
class FilmGeometricFormat:
    """One film gauge's overall size and where its image sits within it.

    `guide_side_margin` is the distance from the film edge with perforations
    a transport mechanism registers off to the nearest edge of the image
    area. `opposite_side_margin` is the same distance on the far edge. For
    every format here except Super 16 the two are equal; Super 16 expands
    its image into the space a second perforation row would occupy, so its
    opposite_side_margin is near zero.
    """

    width: float
    frame_width: float
    frame_height: float
    guide_side_margin: float
    opposite_side_margin: float
    has_sound: bool

    @property
    def guide_side_start(self) -> float:
        """Distance from film centerline to where the guide-side safe margin begins."""
        return self.width / 2 - self.guide_side_margin

    @property
    def opposite_side_start(self) -> float:
        """Same, mirrored to the opposite edge."""
        return -(self.width / 2 - self.opposite_side_margin)

    @property
    def guide_side_band(self) -> tuple[float, float] | None:
        """Where the guide-side safe margin runs, from its start to the film edge.

        None when there is no margin to place a ring on, as with Super 16's
        opposite edge.
        """
        if self.guide_side_margin <= 0:
            return None
        start = self.guide_side_start
        return (start, start + self.guide_side_margin)

    @property
    def opposite_side_band(self) -> tuple[float, float] | None:
        """Same, mirrored to the opposite edge."""
        if self.opposite_side_margin <= 0:
            return None
        start = self.opposite_side_start
        return (start, start - self.opposite_side_margin)


# ANSI/SMPTE 139, ISO 491 raw stock width: 1.377in = 34.976mm
FILM_35MM_WIDTH = 34.976

# Full Aperture ("Silent"), frame centered, no soundtrack.
# Frame 0.980 x 0.735in = 24.89 x 18.67mm.
FILM_35MM_SILENT = FilmGeometricFormat(
    width=FILM_35MM_WIDTH,
    frame_width=24.89,
    frame_height=18.67,
    guide_side_margin=5.04,
    opposite_side_margin=5.04,
    has_sound=False,
)

# Academy sound aperture: the optical soundtrack sits directly against the
# image, inside the frame's old width, not in the margin, so the margin
# measured from real stock matches the silent format above.
FILM_35MM_SOUND = FilmGeometricFormat(
    width=FILM_35MM_WIDTH,
    frame_width=22.05,
    frame_height=16.03,
    guide_side_margin=5.04,
    opposite_side_margin=5.04,
    has_sound=True,
)

# ANSI/SMPTE 109, per Wikipedia's spec table: 0.6280in = 15.950mm
FILM_16MM_WIDTH = 15.950

# Double-perf ("Regular 16"), no soundtrack, perforations on both edges,
# frame centered. Margin confirmed by direct ruler measurement.
FILM_16MM_SILENT = FilmGeometricFormat(
    width=FILM_16MM_WIDTH,
    frame_width=10.26,
    frame_height=7.49,
    guide_side_margin=2.7,
    opposite_side_margin=2.7,
    has_sound=False,
)

# Single-perf, one row of perforations traded for an optical soundtrack
# against the image, same as the 35mm sound case. Margin confirmed by
# direct ruler measurement, both edges.
FILM_16MM_SOUND = FilmGeometricFormat(
    width=FILM_16MM_WIDTH,
    frame_width=9.65,
    frame_height=7.21,
    guide_side_margin=2.7,
    opposite_side_margin=2.7,
    has_sound=True,
)

# Single-perf, image expanded into the space the second perforation row
# would occupy. guide_side_margin matches Standard 16; opposite_side_margin
# is derived, not measured: width - frame_width - guide_side_margin = 0.73,
# Super 16 doesn't use quite all of the freed-up space.
FILM_SUPER16 = FilmGeometricFormat(
    width=FILM_16MM_WIDTH,
    frame_width=12.52,
    frame_height=7.41,
    guide_side_margin=2.7,
    opposite_side_margin=0.73,
    has_sound=False,
)

# Kodak spec: 7.975 +/- 0.040mm
FILM_SUPER8_WIDTH = 7.975

# Single-perf, no sound variant modeled here. Margin is derived, not
# measured: (width - frame_width) / 2 = 1.09
FILM_SUPER8 = FilmGeometricFormat(
    width=FILM_SUPER8_WIDTH,
    frame_width=5.79,
    frame_height=4.01,
    guide_side_margin=1.09,
    opposite_side_margin=1.09,
    has_sound=False,
)
