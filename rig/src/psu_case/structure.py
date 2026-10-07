from dataclasses import dataclass

from psu_case.psu_specs import PSUSpecs

CLEARANCE = 2.0
DEPTH_CLEARANCE = 1.0
ROOFTOP_HEIGHT_CLEARANCE = -1.0


@dataclass(frozen=True)
class MountZoneStructure:
    width: float
    depth: float
    height: float
    wall_thickness: float
    floor_thickness: float
    front_panel_thickness: float

    @property
    def outer_width(self) -> float:
        return self.width + 2 * self.wall_thickness

    @property
    def outer_depth(self) -> float:
        return self.depth + self.front_panel_thickness + self.wall_thickness

    @property
    def outer_height(self) -> float:
        return self.floor_thickness + self.height


@dataclass(frozen=True)
class RooftopStructure:
    height: float


def mount_zone_structure(
    psu: PSUSpecs,
    minimum_width: float,
    minimum_depth: float,
    minimum_height: float,
    wall_thickness: float,
    floor_thickness: float,
    front_panel_thickness: float,
    clearance: float = CLEARANCE,
    depth_clearance: float = DEPTH_CLEARANCE,
) -> MountZoneStructure:
    width = psu.length + 2 * clearance
    if width < minimum_width:
        raise ValueError(
            f"psu-derived width {width} is below the row's minimum {minimum_width}"
        )

    depth = psu.width + depth_clearance
    if depth < minimum_depth:
        raise ValueError(
            f"psu-derived depth {depth} is below the row's minimum {minimum_depth}"
        )

    return MountZoneStructure(
        width=width,
        depth=depth,
        height=minimum_height,
        wall_thickness=wall_thickness,
        floor_thickness=floor_thickness,
        front_panel_thickness=front_panel_thickness,
    )


def rooftop_structure(
    psu: PSUSpecs,
    height_clearance: float = ROOFTOP_HEIGHT_CLEARANCE,
) -> RooftopStructure:
    return RooftopStructure(height=psu.height + height_clearance)


@dataclass(frozen=True)
class CaseStructure:
    mount_zone: MountZoneStructure
    rooftop: RooftopStructure

    def back_wall_height(self, ceiling_thickness: float) -> float:
        return (
            self.mount_zone.floor_thickness
            + self.mount_zone.height
            + ceiling_thickness
            + self.rooftop.height
        )
