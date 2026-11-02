from dataclasses import dataclass
from enum import Enum, auto


class PSUFace(Enum):
    """A face of the PSU that has screw holes. The case puts a wall against each one.

    FLOOR is the PSU's underside. BACK is the side that it stands against.
    """

    FLOOR = auto()
    BACK = auto()


@dataclass(frozen=True)
class PSUScrewHole:
    """One of the PSU's screw holes, placed in its own face's coordinates.

    Attributes:
        face: which face of the PSU the hole opens on.
        along: distance from the front of the PSU, along the PSU's length. Shared by both
            faces, so a floor hole and a back hole at the same `along` line up.
        across: distance from the reference edge, across the face. From the
            rightmost edge on FLOOR, up from the floor on BACK.
        is_tapped: whether the hole is threaded on the PSU's side, so a screw
            entering it bites into the PSU itself. False where the hole is a
            plain passthrough and the thread it needs is somewhere beyond.
        thread: the screw the hole takes, as a metric designation.
    """

    face: PSUFace
    along: float
    across: float
    is_tapped: bool = True
    thread: str = "M3"


@dataclass(frozen=True)
class PSUSpecs:
    length: float
    width: float
    height: float
    screw_holes: tuple[PSUScrewHole, ...] = ()


# Measured with the case facing us and the PSU facing right, from its lowest,
# front, rightmost point.
PSU = PSUSpecs(
    length=160.0,
    width=98.0,
    height=42.0,
    screw_holes=(
        PSUScrewHole(face=PSUFace.FLOOR, along=3.0, across=91.5, is_tapped=False),
        PSUScrewHole(face=PSUFace.FLOOR, along=157.0, across=6.5, is_tapped=False),
        PSUScrewHole(face=PSUFace.FLOOR, along=5.0, across=5.0),
        PSUScrewHole(face=PSUFace.FLOOR, along=148.0, across=5.0),
        PSUScrewHole(face=PSUFace.FLOOR, along=24.0, across=65.0),
        PSUScrewHole(face=PSUFace.FLOOR, along=102.0, across=65.0),
        PSUScrewHole(face=PSUFace.BACK, along=7.0, across=28.0, is_tapped=False),
        PSUScrewHole(face=PSUFace.BACK, along=22.0, across=20.0),
        PSUScrewHole(face=PSUFace.BACK, along=139.0, across=10.5),
        PSUScrewHole(face=PSUFace.BACK, along=157.0, across=29.0, is_tapped=False),
    ),
)
