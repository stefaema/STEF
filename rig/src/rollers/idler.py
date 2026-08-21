from typing import cast

from bearings.core import BearingCore
from build123d import (
    Axis,
    Cylinder,
    Line,
    Part,
    Plane,
    Pos,
    SagittaArc,
    make_face,
    revolve,
)

CORD_DIAMETER = 2.0
GUIDE_LIP = 1.0
FILM_CLEARANCE = 0.1

FILM_35_HALF_WIDTH = 17.5
GROOVE_35_CENTRE = 16.5
GROOVE_35_SURFACE_DIAMETER = 38.0
FLANGE_THICKNESS = 2.0

FILM_16_HALF_WIDTH = 8.0
GROOVE_16_CENTRE = 7.0
GROOVE_16_SURFACE_DIAMETER = 30.0
DISC_16_THICKNESS = 1.0

WAIST_DIAMETER = 29.0
CENTRE_CURVE_SAGITTA = 0.5
SIDE_CURVE_SAGITTA = 0.5

GROOVE_35_BOTTOM_DIAMETER = GROOVE_35_SURFACE_DIAMETER - CORD_DIAMETER
CROWN_35_DIAMETER = GROOVE_35_SURFACE_DIAMETER + CORD_DIAMETER
FLANGE_DIAMETER = CROWN_35_DIAMETER + 2 * GUIDE_LIP
FLANGE_FACE = FILM_35_HALF_WIDTH + FILM_CLEARANCE

GROOVE_16_BOTTOM_DIAMETER = GROOVE_16_SURFACE_DIAMETER - CORD_DIAMETER
CROWN_16_DIAMETER = GROOVE_16_SURFACE_DIAMETER + CORD_DIAMETER
DISC_16_DIAMETER = CROWN_16_DIAMETER + 2 * GUIDE_LIP
DISC_16_FACE = FILM_16_HALF_WIDTH + FILM_CLEARANCE

HALF_LENGTH = FLANGE_FACE + FLANGE_THICKNESS
LENGTH = 2 * HALF_LENGTH

CUT_RADIUS = FLANGE_DIAMETER


class IdlerRoller:
    def __init__(
        self,
        groove_35_centre: float = GROOVE_35_CENTRE,
        groove_16_centre: float = GROOVE_16_CENTRE,
    ) -> None:
        half_cord = CORD_DIAMETER / 2
        if groove_35_centre + half_cord > FLANGE_FACE:
            raise ValueError(
                f"35mm groove at {groove_35_centre} runs past the flange at {FLANGE_FACE}"
            )
        if groove_16_centre + half_cord > DISC_16_FACE:
            raise ValueError(
                f"16mm groove at {groove_16_centre} runs past the disc at {DISC_16_FACE}"
            )
        self.groove_35_centre = groove_35_centre
        self.groove_16_centre = groove_16_centre
        self.core = BearingCore(length=LENGTH, at=(0.0, 0.0, -HALF_LENGTH))
        if self.core.min_shell_diameter > WAIST_DIAMETER:
            raise ValueError(
                f"core {self.core.min_shell_diameter} pokes through the waist {WAIST_DIAMETER}"
            )

    @property
    def groove_35_span(self) -> tuple[float, float]:
        half_cord = CORD_DIAMETER / 2
        return (self.groove_35_centre - half_cord, self.groove_35_centre + half_cord)

    @property
    def groove_16_span(self) -> tuple[float, float]:
        half_cord = CORD_DIAMETER / 2
        return (self.groove_16_centre - half_cord, self.groove_16_centre + half_cord)

    def barrel(self) -> Part:
        flange = FLANGE_DIAMETER / 2
        surface_35 = GROOVE_35_SURFACE_DIAMETER / 2
        disc = DISC_16_DIAMETER / 2
        surface_16 = GROOVE_16_SURFACE_DIAMETER / 2

        side_curve_end = self.groove_35_span[0]
        centre_curve_end = self.groove_16_span[0]
        disc_outer = DISC_16_FACE + DISC_16_THICKNESS

        outline = [
            (flange, -HALF_LENGTH),
            (flange, -FLANGE_FACE),
            (surface_35, -FLANGE_FACE),
            (surface_35, -side_curve_end),
            (disc, -disc_outer),
            (disc, -DISC_16_FACE),
            (surface_16, -DISC_16_FACE),
            (surface_16, -centre_curve_end),
            (surface_16, centre_curve_end),
            (surface_16, DISC_16_FACE),
            (disc, DISC_16_FACE),
            (disc, disc_outer),
            (surface_35, side_curve_end),
            (surface_35, FLANGE_FACE),
            (flange, FLANGE_FACE),
            (flange, HALF_LENGTH),
            (0.0, HALF_LENGTH),
            (0.0, -HALF_LENGTH),
        ]

        edges = []
        for start, end in zip(outline, outline[1:] + outline[:1]):
            if {start, end} == {outline[3], outline[4]}:
                edges.append(SagittaArc(start, end, SIDE_CURVE_SAGITTA))
            elif {start, end} == {outline[11], outline[12]}:
                edges.append(SagittaArc(start, end, SIDE_CURVE_SAGITTA))
            elif {start, end} == {outline[7], outline[8]}:
                edges.append(SagittaArc(start, end, CENTRE_CURVE_SAGITTA))
            else:
                edges.append(Line(start, end))

        profile = edges[0]
        for edge in edges[1:]:
            profile += edge
        return revolve((Plane.XZ * make_face(profile)).faces(), Axis.Z)

    def grooves(self) -> Part:
        cutters = []
        for span, bottom in (
            (self.groove_35_span, GROOVE_35_BOTTOM_DIAMETER),
            (self.groove_16_span, GROOVE_16_BOTTOM_DIAMETER),
        ):
            width = span[1] - span[0]
            ring = Cylinder(CUT_RADIUS, width) - Cylinder(bottom / 2, width)
            centre = (span[0] + span[1]) / 2
            cutters.append(Pos(0.0, 0.0, centre) * ring)
            cutters.append(Pos(0.0, 0.0, -centre) * ring)
        cut = cutters[0]
        for extra in cutters[1:]:
            cut += extra
        return cut

    def build(self) -> Part:
        return cast(Part, self.barrel() - self.grooves() - self.core.cutters())


def sample() -> Part:
    return IdlerRoller().build()
