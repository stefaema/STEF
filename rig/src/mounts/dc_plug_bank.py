from build123d import Part

from mounts.dc_barrel_jack import DCBarrelJackMount
from rig.materials import Material

DEFAULT_COUNT = 4


def sample(material: Material = Material.PLA, count: int = DEFAULT_COUNT) -> Part:
    return DCBarrelJackMount.banked_sample(
        count=count,
        panel_thickness=3.0,
        material=material,
    )
