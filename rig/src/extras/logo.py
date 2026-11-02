from pathlib import Path
from typing import cast

from build123d import Compound, Face, Part, Pos, extrude, import_svg, scale

LOGO_SVG = Path(__file__).resolve().parents[3] / "boards" / "transport" / "logo.svg"

CUT_OVERSHOOT = 0.5


class LogoEngraving:
    """The STEF logo sunk into a face with its centre at `at` on that face."""

    def __init__(
        self, at: tuple[float, float, float], width: float, depth: float
    ) -> None:
        self.at = at
        self.width = width
        self.depth = depth

    def cutout(self) -> Part:
        """Solid to subtract to leave the logo `depth` deep, `width` across x."""
        faces = [shape for shape in import_svg(LOGO_SVG) if isinstance(shape, Face)]
        drawing = Compound(faces)
        sized = scale(drawing, self.width / drawing.bounding_box().size.X)
        centre = sized.bounding_box().center()
        pocket = Part()
        for face in sized.faces():
            pocket += extrude(face, self.depth + CUT_OVERSHOOT)
        x, y, z = self.at
        return cast(Part, Pos(x - centre.X, y - centre.Y, z - self.depth) * pocket)
