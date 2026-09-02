from dataclasses import dataclass


@dataclass(frozen=True)
class TimingBeltSpec:
    """Specifies the groove a timing belt's tooth sits in.

    A groove is the tooth's negative with a little clearance.

    Its shape is a root arc at the bottom, a sloped flank up each side, and a
    flat tip between one groove and the next.

    Every measurement is in millimeters, taken with the belt lying flat. Those
    along its length are measured on the pitch line, which the belt's tensile
    cords (the fiberglass running through its back) run along.

    Attributes:
        name: the belt profile's trade name.
        pitch: tooth-to-tooth distance along the pitch line.
        pitch_line_offset: the gap from the tooth tips out to the pitch line.
            Called PLD in the belt tables, for pitch line differential.
        groove_mouth_width: the groove's opening, where the root arc gives way
            to the flanks.
        flank_run: how far one flank travels along the belt.
        flank_drop: how far one flank travels radially, from the tip surface
            down to the root arc.
        groove_radius: the root arc's own radius.
    """

    name: str
    pitch: float
    pitch_line_offset: float
    groove_mouth_width: float
    flank_run: float
    flank_drop: float
    groove_radius: float


GT2_2MM = TimingBeltSpec(
    name="GT2",
    pitch=2.0,
    pitch_line_offset=0.3,
    groove_mouth_width=1.28,
    flank_run=0.1,
    flank_drop=0.375,
    groove_radius=0.675,
)
