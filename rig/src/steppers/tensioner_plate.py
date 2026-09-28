# Needs refactor, too large. For now it stays as is.

from enum import Enum
from typing import cast

from build123d import (
    Align,
    Box,
    Cylinder,
    Part,
    Plane,
    Pos,
    SlotCenterToCenter,
    extrude,
)
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK, SCREW_M5_COUNTERSUNK

from steppers.stepper_specs import NEMA_17, NemaStepperSpec

PLATE_THICKNESS = 5.0

MOTOR_SCREW = SCREW_M3_COUNTERSUNK
SLOT_BOLT = SCREW_M5_COUNTERSUNK

BOSS_RADIAL_CLEARANCE = 1.0  # per side, between the boss and the bore
MOUTH_WIDTH_CLEARANCE = 0.4  # across the mouth, total: the boss just passes
MINIMUM_LAND = 4.0  # flat plate the motor face bears on, outside the opening
MINIMUM_MOUTH_MARGIN = 1.0  # plate left between a sunk screw head and the mouth
MINIMUM_WALL = 2.5  # plate left between the slot and any arm edge

ARM_LENGTH = 32.0
ARM_WIDTH = 32.0
SLOT_TRAVEL = 10.0

CUT_OVERSHOOT = 0.5


class ArmSide(Enum):
    Y_POS = 1.0
    Y_NEG = -1.0

    @property
    def sign(self) -> float:
        return self.value


class MotorPlate:
    def __init__(
        self,
        stepper: NemaStepperSpec = NEMA_17,
        thickness: float = PLATE_THICKNESS,
    ) -> None:
        self.stepper = stepper
        self.thickness = thickness
        self.screw = ScrewHole(spec=MOTOR_SCREW, sink_head=True)
        self.opening_radius = stepper.boss_diameter / 2 + BOSS_RADIAL_CLEARANCE
        self.mouth_width = stepper.boss_diameter + MOUTH_WIDTH_CLEARANCE

        land = stepper.face_size / 2 - self.opening_radius
        if land < MINIMUM_LAND:
            raise ValueError(
                f"opening radius {self.opening_radius} leaves {land} of land on a "
                f"{stepper.face_size} face, below MINIMUM_LAND {MINIMUM_LAND}"
            )

        margin = (
            stepper.bolt_spacing / 2 - self.mouth_width / 2 - self.screw.head_radius
        )
        if margin < MINIMUM_MOUTH_MARGIN:
            raise ValueError(
                f"a sunk head on the open side leaves {margin} to the "
                f"{self.mouth_width}-wide mouth, below MINIMUM_MOUTH_MARGIN "
                f"{MINIMUM_MOUTH_MARGIN}"
            )
        self.mouth_margin = margin

    @property
    def edge(self) -> float:
        return self.stepper.face_size / 2

    def body(self) -> Part:
        return Box(
            self.stepper.face_size,
            self.stepper.face_size,
            self.thickness,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )

    def opening_cutter(self) -> Part:
        """Solid to subtract for the boss, opened to one edge so it is a U, not an O.

        The bore clears the boss on all sides. The mouth is the gap joining that
        bore to the plate's edge, only just wide enough for the boss to pass.
        """
        bore = Cylinder(
            self.opening_radius,
            self.thickness + 2 * CUT_OVERSHOOT,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        mouth = Pos(0.0, -self.mouth_width / 2, 0.0) * Box(
            self.edge + CUT_OVERSHOOT,
            self.mouth_width,
            self.thickness + 2 * CUT_OVERSHOOT,
            align=(Align.MIN, Align.MIN, Align.MIN),
        )
        return cast(Part, Pos(0.0, 0.0, -CUT_OVERSHOOT) * (bore + mouth))

    def screw_cutters(self) -> list[Part]:
        return [
            ScrewHole(
                at=(x, y, self.thickness), spec=MOTOR_SCREW, sink_head=True
            ).cutter(self.thickness + CUT_OVERSHOOT)
            for x, y in self.stepper.bolt_positions
        ]

    def build(self) -> Part:
        solid = self.body() - self.opening_cutter()
        for cutter in self.screw_cutters():
            solid -= cutter
        return cast(Part, solid)


class SlottedArm:
    def __init__(
        self,
        thickness: float = PLATE_THICKNESS,
        at_y: float = 0.0,
        side: ArmSide = ArmSide.Y_NEG,
        length: float = ARM_LENGTH,
        width: float = ARM_WIDTH,
        travel: float = SLOT_TRAVEL,
    ) -> None:
        self.thickness = thickness
        self.at_y = at_y
        self.side = side
        self.length = length
        self.width = width
        self.travel = travel
        self.slot_width = SLOT_BOLT.thread.clearance_bore
        self.slot_length = travel + self.slot_width

        if length < self.slot_width + 2 * MINIMUM_WALL:
            raise ValueError(
                f"length {length} cannot carry a {self.slot_width}-wide slot with "
                f"MINIMUM_WALL {MINIMUM_WALL} each side"
            )
        if width < self.slot_length + 2 * MINIMUM_WALL:
            raise ValueError(
                f"width {width} cannot carry a {self.slot_length}-long slot with "
                f"MINIMUM_WALL {MINIMUM_WALL} at each end"
            )

    @property
    def center_y(self) -> float:
        return self.at_y + self.side.sign * self.length / 2

    @property
    def far_edge(self) -> float:
        return self.at_y + self.side.sign * self.length

    def body(self) -> Part:
        return cast(
            Part,
            Pos(0.0, self.at_y, 0.0)
            * Box(
                self.width,
                self.length,
                self.thickness,
                align=(
                    Align.CENTER,
                    Align.MAX if self.side is ArmSide.Y_NEG else Align.MIN,
                    Align.MIN,
                ),
            ),
        )

    def slot_cutter(self) -> Part:
        profile = Pos(0.0, self.center_y) * SlotCenterToCenter(
            self.travel, self.slot_width
        )
        return cast(
            Part,
            Pos(0.0, 0.0, -CUT_OVERSHOOT)
            * extrude(Plane.XY * profile, self.thickness + 2 * CUT_OVERSHOOT),
        )

    def build(self) -> Part:
        return cast(Part, self.body() - self.slot_cutter())


class TensionerPlate:
    def __init__(
        self,
        stepper: NemaStepperSpec = NEMA_17,
        side: ArmSide = ArmSide.Y_NEG,
        thickness: float = PLATE_THICKNESS,
        travel: float = SLOT_TRAVEL,
    ) -> None:
        self.side = side
        self.plate = MotorPlate(stepper=stepper, thickness=thickness)
        self.arm = SlottedArm(
            thickness=thickness,
            at_y=side.sign * self.plate.edge,
            side=side,
            width=stepper.face_size,
            travel=travel,
        )

    @property
    def slot_center_y(self) -> float:
        return self.arm.center_y

    @property
    def length(self) -> float:
        return self.plate.edge + abs(self.arm.far_edge)

    def build(self) -> Part:
        return cast(Part, self.plate.build() + self.arm.build())


def build() -> dict[str, Part]:
    return {side.name.lower(): TensionerPlate(side=side).build() for side in ArmSide}


def sample() -> Part:
    return MotorPlate().build()
