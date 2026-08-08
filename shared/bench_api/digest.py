"""What a call will put on the wire, shown before it goes."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    """A named run of bytes inside a layer's body. How it is drawn is the GUI's."""

    name: str
    start: int
    length: int


@dataclass(frozen=True, slots=True)
class Button:
    """Something that can be done with the layer that carries it."""

    label: str
    call: str
    hazardous: bool = False
    closes: bool = False


@dataclass(frozen=True, slots=True)
class Layer:
    """One panel of a digest: some bytes, and what they are."""

    title: str
    body: bytes | str
    legend: tuple[Span, ...] = ()
    editable: bool = False
    buttons: tuple[Button, ...] = ()


@dataclass(frozen=True, slots=True)
class Digest:
    """Every layer of one call, outermost first.

    A producer is `(values) -> Digest` and takes no link, so opening one fires
    nothing: there is nothing in the signature to fire.
    """

    layers: tuple[Layer, ...]
    buttons: tuple[Button, ...] = ()
