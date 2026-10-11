from dataclasses import dataclass
from typing import cast

from build123d import Part
from steppers.shaft_hub import END_DEPTH, ShaftHub

from rig.materials import Material
from rollers.film_roller import FilmRoller, total_length
from rollers.gauges import FilmRollerGauge
from rollers.idler import GAUGE_8, GAUGE_16, GAUGE_35


@dataclass(frozen=True)
class MotionRoller:
    """One roller variant driven straight off a stepper's shaft, through a ShaftHub at its bottom end."""

    name: str
    gauges: list[FilmRollerGauge]
    two_piece: bool = False

    def _core(self, material: Material) -> ShaftHub:
        length = total_length(self.gauges, END_DEPTH)
        return ShaftHub(length=length, material=material, at=(0.0, 0.0, -length / 2))

    def build(self, material: Material = Material.PLA) -> Part | dict[str, Part]:
        roller = FilmRoller(gauges=self.gauges, core=self._core(material))
        if self.two_piece:
            female, male = roller.build_two_piece()
            return {"female": female, "male": male}
        return cast(Part, roller.build_one_piece())


MOTION_ROLLERS = [
    MotionRoller(
        name="8mm_16mm_35mm_two_piece",
        gauges=[GAUGE_8, GAUGE_16, GAUGE_35],
        two_piece=True,
    ),
]


def build(material: Material = Material.PLA) -> dict[str, Part]:
    result: dict[str, Part] = {}
    for roller in MOTION_ROLLERS:
        produced = roller.build(material)
        if isinstance(produced, dict):
            for variant, part in produced.items():
                result[f"{roller.name}_{variant}"] = part
        else:
            result[roller.name] = produced
    return result
