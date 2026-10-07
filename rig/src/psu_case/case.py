from dataclasses import dataclass

from mounts import dc_barrel_jack, rocker_switch, wago_222
from mounts.c14 import C14Mount
from mounts.dc_barrel_jack import DCBarrelJackMount
from mounts.rocker_switch import RockerSwitchMount

from psu_case import structure
from psu_case.mount_zone import SPACER_X, SPACER_Y, Layout, MountZone, ResolvedLayout
from psu_case.psu_specs import PSU
from rig.materials import Material

WALL_THICKNESS = 5.0
FLOOR_THICKNESS = 5.0
FRONT_PANEL_THICKNESS = 3.0

DC_JACK_COUNT = 4


def _bank_width(count: int, channel_width: float, sidewall_thickness: float) -> float:
    return count * (channel_width + sidewall_thickness) - sidewall_thickness


def front_panel_layout(material: Material) -> Layout:
    bank_width = _bank_width(
        DC_JACK_COUNT,
        dc_barrel_jack.CHANNEL_WIDTH[material],
        dc_barrel_jack.SIDEWALL_THICKNESS[material],
    )
    return (
        SPACER_Y,
        SPACER_Y,
        C14Mount.CHANNEL_WIDTH,
        SPACER_Y,
        rocker_switch.CUTOUT_WIDTH[material],
        SPACER_Y,
        SPACER_Y,
        bank_width,
        SPACER_Y,
        SPACER_Y,
    )


C14_INDEX = 2
ROCKER_INDEX = 4
JACK_BANK_INDEX = 7


def distance_layout_3wago() -> Layout:
    return (C14Mount.CHANNEL_LENGTH, SPACER_X, wago_222.CHANNEL_WIDTH_3CABLE, 10.0)


def distance_layout_5wago_pair() -> Layout:
    return (
        DCBarrelJackMount.CHANNEL_LENGTH,
        SPACER_X,
        wago_222.CHANNEL_WIDTH_5CABLE,
        10.0,
    )


def minimum_height() -> float:
    return max(
        C14Mount.CHANNEL_HEIGHT,
        DCBarrelJackMount.CHANNEL_HEIGHT,
        RockerSwitchMount.CHANNEL_HEIGHT,
        wago_222.Wago222Mount.CHANNEL_HEIGHT,
    )


@dataclass(frozen=True)
class CaseLayout:
    structure: structure.CaseStructure
    front_panel: ResolvedLayout
    wago_3: ResolvedLayout
    wago_5_pair: ResolvedLayout


def layout(material: Material = Material.PLA) -> CaseLayout:
    front_panel = front_panel_layout(material)
    wago_3 = distance_layout_3wago()
    wago_5_pair = distance_layout_5wago_pair()

    mount_zone = structure.mount_zone_structure(
        psu=PSU,
        minimum_width=MountZone.get_minimum_width(front_panel),
        minimum_depth=MountZone.get_minimum_depth(wago_3, wago_5_pair),
        minimum_height=minimum_height(),
        wall_thickness=WALL_THICKNESS,
        floor_thickness=FLOOR_THICKNESS,
        front_panel_thickness=FRONT_PANEL_THICKNESS,
    )
    case_structure = structure.CaseStructure(
        mount_zone=mount_zone,
        rooftop=structure.rooftop_structure(PSU),
    )

    resolved = MountZone.solve(
        front_panel,
        wago_3,
        wago_5_pair,
        structure_width=mount_zone.outer_width,
        structure_depth=mount_zone.outer_depth,
        front_panel_thickness=mount_zone.front_panel_thickness,
        case_wall_thickness=mount_zone.wall_thickness,
    )

    return CaseLayout(
        structure=case_structure,
        front_panel=resolved["front_panel"],
        wago_3=resolved["wago_3"],
        wago_5_pair=resolved["wago_5_pair"],
    )
