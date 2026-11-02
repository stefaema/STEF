"""The shoebox and lid that every board case shares.

The frame is the interior's: x runs from one end wall's inner face to the
other's, y runs across them, and z = 0 is the ground the shoebox stands on.

The connectors stand on the floor and break out through the walls. The board
rests above them, and a lid screwed into four corner posts closes the story
above the board. Each case brings what holds its own board and what it cuts
through its walls.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from build123d import Align, Box, Cylinder, Part, Pos
from fasteners.heat_insert import HeatInsert, InsertFacing
from fasteners.insert_specs import INSERT_M3_SHORT
from fasteners.screw import ScrewHole
from fasteners.screw_specs import SCREW_M3_COUNTERSUNK, SCREW_M5_COUNTERSUNK
from mounts.side_panel import SidePanelMount

from rig.materials import Material

WALL_THICKNESS = 3.0  # the panel the RJ45 and jack samples were fitted against
FLOOR_THICKNESS = 3.0
UPPER_HEIGHT = 30.0  # board's top face to the lid
BOARD_UNDERSIDE_CLEARANCE = 3.0  # above the tallest channel, for the board's leads

LID_THICKNESS = 3.0
LID_SCREW = SCREW_M3_COUNTERSUNK
LID_INSERT = INSERT_M3_SHORT
LID_SCREW_LENGTH = 8.0  # under the head
CLAMP_SQUEEZE = 0.2

TAB_SCREW = SCREW_M5_COUNTERSUNK
TAB_THICKNESS = 5.0
TAB_WIDTH = 20.0  # along x
TAB_REACH = 16.0  # out from the wall's outer face

CUT_OVERSHOOT = 0.5


def slab(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> Part:
    return cast(
        Part,
        Pos(x0, y0, z0)
        * Box(x1 - x0, y1 - y0, z1 - z0, align=(Align.MIN, Align.MIN, Align.MIN)),
    )


def cutout_centre(mount: SidePanelMount) -> float:
    """Height of a mount's cutout centre above its own channel floor."""
    box = mount.cutout().bounding_box()
    return (box.min.Z + box.max.Z) / 2


def floor_level_with(reference: SidePanelMount, mount: SidePanelMount) -> float:
    """The floor height that puts `mount`'s cutout centre level with `reference`'s.

    Both are measured at the origin. It raises if `mount` would have to sink
    into the floor.
    """
    floor = FLOOR_THICKNESS + cutout_centre(reference) - cutout_centre(mount)
    if floor < FLOOR_THICKNESS:
        raise ValueError(
            f"the {type(mount).__name__}'s cutout centre sits above the "
            f"{type(reference).__name__}'s, so lining them up would sink it "
            f"{FLOOR_THICKNESS - floor} into the floor"
        )
    return floor


def clear_above(mounts: Iterable[SidePanelMount]) -> float:
    """Height that clears the tallest channel or cutout by the board leads' room."""
    tallest = FLOOR_THICKNESS
    for mount in mounts:
        tallest = max(
            tallest,
            mount.body().bounding_box().max.Z,
            mount.cutout().bounding_box().max.Z,
        )
    return tallest + BOARD_UNDERSIDE_CLEARANCE


def wall_top(board_top: float) -> float:
    """Height of the walls and posts. The lid's underside sits on them."""
    return board_top + UPPER_HEIGHT


def hanging_pillars(
    points: Iterable[tuple[float, float]], diameter: float, length: float
) -> Part:
    """Round pillars that hang `length` down from z = 0 under the lid."""
    pillars = Part()
    for x, y in points:
        pillars += Pos(x, y, -length) * Cylinder(
            diameter / 2, length, align=(Align.CENTER, Align.CENTER, Align.MIN)
        )
    return pillars


@dataclass(frozen=True)
class Shoebox:
    """A shoebox sized by its interior. It has a lid post at each corner and a tab on each long wall."""

    interior_length: float
    interior_width: float

    def outer_extent(self) -> tuple[float, float, float, float]:
        """The shoebox's rectangle in plan, as `(x0, x1, y0, y1)`. The lid shares it."""
        return (
            -WALL_THICKNESS,
            self.interior_length + WALL_THICKNESS,
            -WALL_THICKNESS,
            self.interior_width + WALL_THICKNESS,
        )

    def post_half_side(self) -> float:
        """Half a lid post's side. It equals the insert's boss radius, so the pocket has a wall all round."""
        return HeatInsert(spec=LID_INSERT).boss_radius

    def post_points(self) -> tuple[tuple[float, float], ...]:
        """The four lid posts' centres, as `(x, y)`.

        Each post continues a long wall past an end wall's outer face, and its
        outer face is flush with that long wall's. The posts stand out along x
        only, so the outline in plan reads as an H and no post takes anything
        from the interior.
        """
        half = self.post_half_side()
        x0 = -WALL_THICKNESS - half
        x1 = self.interior_length + WALL_THICKNESS + half
        y0 = -WALL_THICKNESS + half
        y1 = self.interior_width + WALL_THICKNESS - half
        return ((x0, y0), (x1, y0), (x0, y1), (x1, y1))

    def plan_rectangles(self) -> list[tuple[float, float, float, float]]:
        """The shoebox's outline in plan, as `(x0, x1, y0, y1)` rectangles for the walls and each post.

        The lid is cut to the same outline, so it covers the posts and nothing more.
        """
        half = self.post_half_side()
        return [self.outer_extent()] + [
            (x - half, x + half, y - half, y + half) for x, y in self.post_points()
        ]

    def _shell(self, top: float) -> Part:
        """Floor and four walls, open on top."""
        x0, x1, y0, y1 = self.outer_extent()
        outer = slab(x0, x1, y0, y1, 0.0, top)
        hollow = slab(
            0.0,
            self.interior_length,
            0.0,
            self.interior_width,
            FLOOR_THICKNESS,
            top + CUT_OVERSHOOT,
        )
        return cast(Part, outer - hollow)

    def _posts(self, top: float) -> Part:
        """A square post at each corner, from the ground to the wall top, carrying a lid insert."""
        half = self.post_half_side()
        posts = Part()
        for x, y in self.post_points():
            posts += slab(x - half, x + half, y - half, y + half, 0.0, top)
        return posts

    def _post_inserts(self, top: float, material: Material) -> Part:
        insert = HeatInsert(
            spec=LID_INSERT, facing=InsertFacing.DOWN, material=material
        )
        bore = insert.bore_depth_for(LID_SCREW_LENGTH - LID_THICKNESS)
        cutters = Part()
        for x, y in self.post_points():
            cutters += Pos(x, y, top) * insert.cutter(bore)
        return cutters

    def _tab_centres(self) -> tuple[tuple[float, float], ...]:
        """The table screws, one in each tab, as `(x, y)`."""
        _, _, y0, y1 = self.outer_extent()
        x = self.interior_length / 2
        return ((x, y0 - TAB_REACH / 2), (x, y1 + TAB_REACH / 2))

    def _tabs(self) -> Part:
        """Two flanges that stand out of the long walls at the ground."""
        _, _, y0, y1 = self.outer_extent()
        x = self.interior_length / 2
        x0, x1 = x - TAB_WIDTH / 2, x + TAB_WIDTH / 2
        return cast(
            Part,
            slab(x0, x1, y0 - TAB_REACH, y0, 0.0, TAB_THICKNESS)
            + slab(x0, x1, y1, y1 + TAB_REACH, 0.0, TAB_THICKNESS),
        )

    def _tab_holes(self) -> Part:
        screw = ScrewHole(spec=TAB_SCREW, sink_head=True)
        cutters = Part()
        for x, y in self._tab_centres():
            cutters += Pos(x, y, TAB_THICKNESS) * screw.cutter(
                TAB_THICKNESS + CUT_OVERSHOOT
            )
        return cutters

    def _plinths(self, mounts: Sequence[SidePanelMount]) -> Part:
        """A block under each raised mount, from the floor up to its channel. The channel has no floor of its own."""
        plinths = Part()
        for mount in mounts:
            box = mount.body().bounding_box()
            if box.min.Z > FLOOR_THICKNESS:
                plinths += slab(
                    box.min.X,
                    box.max.X,
                    box.min.Y,
                    box.max.Y,
                    FLOOR_THICKNESS,
                    box.min.Z,
                )
        return plinths

    def body(
        self,
        top: float,
        mounts: Sequence[SidePanelMount],
        holders: Part,
        openings: Part,
        material: Material,
    ) -> Part:
        """The shoebox up to `top`, with the connectors in it and open on top.

        `holders` are whatever keeps the board in place. `openings` are cut
        through the walls after the connectors' own cutouts.
        """
        bodies, cutouts = Part(), Part()
        for mount in mounts:
            bodies += mount.body()
            cutouts += mount.cutout()

        solid = self._shell(top) + self._posts(top) + self._tabs()
        solid += holders + self._plinths(mounts) + bodies
        solid -= cutouts
        solid -= openings
        solid -= self._post_inserts(top, material)
        solid -= self._tab_holes()
        return cast(Part, solid)

    def lid(self, pillars: Part) -> Part:
        """A plate screwed into the corner posts, with `pillars` hanging under it.

        Its underside is z = 0, which sits on the shoebox's wall top.
        """
        plate = Part()
        for x0, x1, y0, y1 in self.plan_rectangles():
            plate += slab(x0, x1, y0, y1, 0.0, LID_THICKNESS)
        solid = plate + pillars

        screw = ScrewHole(spec=LID_SCREW, sink_head=True)
        for x, y in self.post_points():
            solid -= Pos(x, y, LID_THICKNESS) * screw.cutter(
                LID_THICKNESS + CUT_OVERSHOOT
            )
        return cast(Part, solid)
