"""Which print material a part is modeled for.

A part's own geometry never changes with material. A handful of small
allowances do: a cutout that seats a connector, a rib that holds a press fit,
a wall that resists bowing under one. Those live as material-keyed dicts next
to the geometry they adjust, rather than as a single scale applied in the
slicer.
"""

from enum import Enum


class Material(Enum):
    PLA = "pla"
    PETG = "petg"

    @classmethod
    def parse(cls, name: str) -> "Material":
        try:
            return cls(name.lower())
        except ValueError:
            choices = ", ".join(member.value for member in cls)
            raise ValueError(
                f"unknown material {name!r}, choose from {choices}"
            ) from None
