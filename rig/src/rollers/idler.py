"""Idler roller geometry, rebuilt around film_formats and oring_specs."""

from dataclasses import dataclass
from typing import cast

from bearings.core import BearingCore
from bearings.seat import BearingSeat
from build123d import Part

from rollers.film_roller import FilmRoller, total_length
from rollers.gauges import FilmRollerGauge
from shared.film_formats import FILM_16MM_SILENT, FILM_35MM_SILENT, FILM_SUPER8

# Track diameters, narrow to wide. TRACK_8 sits well above the 27.6mm a
# BearingSeat's default boss_radius needs to clear (see BearingSeat.boss_radius).
# Each step up is at least 6mm of diameter (3mm of radius each side), so a
# narrower gauge's limiting flange (LIMIT_FLANGE_MARGIN in film_roller.py)
# always clears the next gauge's own track radius.
TRACK_8_DIAMETER = 28.0
TRACK_16_DIAMETER = 34.0
TRACK_35_DIAMETER = 40.0

GAUGE_8 = FilmRollerGauge(film_format_spec=FILM_SUPER8, track_diameter=TRACK_8_DIAMETER)
GAUGE_16 = FilmRollerGauge(
    film_format_spec=FILM_16MM_SILENT, track_diameter=TRACK_16_DIAMETER
)
GAUGE_35 = FilmRollerGauge(
    film_format_spec=FILM_35MM_SILENT, track_diameter=TRACK_35_DIAMETER
)


@dataclass(frozen=True)
class Idler:
    """One idler variant: which gauges it carries, and whether it prints in two pieces."""

    name: str
    gauges: list[FilmRollerGauge]
    two_piece: bool = False

    def _core(self) -> BearingCore:
        seat = BearingSeat()
        length = total_length(self.gauges, seat.depth)
        return BearingCore(length=length, seat=seat, at=(0.0, 0.0, -length / 2))

    def build(self) -> Part | dict[str, Part]:
        roller = FilmRoller(gauges=self.gauges, core=self._core())
        if self.two_piece:
            female, male = roller.build_two_piece()
            return {"female": female, "male": male}
        return cast(Part, roller.build_one_piece())


IDLERS = [
    # Idler(name="8mm", gauges=[GAUGE_8]),
    # Idler(name="16mm", gauges=[GAUGE_16]),
    # Idler(name="35mm", gauges=[GAUGE_35]),
    # Parked while the film_roller rework above settles: single-gauge and
    # O-ring idlers, re-enable once the combined one checks out.
    Idler(name="8mm_16mm_35mm", gauges=[GAUGE_8, GAUGE_16, GAUGE_35]),
    Idler(
        name="8mm_16mm_35mm_two_piece",
        gauges=[GAUGE_8, GAUGE_16, GAUGE_35],
        two_piece=True,
    ),
]


def build() -> dict[str, Part]:
    result: dict[str, Part] = {}
    for idler in IDLERS:
        produced = idler.build()
        if isinstance(produced, dict):
            for variant, part in produced.items():
                result[f"{idler.name}_{variant}"] = part
        else:
            result[idler.name] = produced
    return result
