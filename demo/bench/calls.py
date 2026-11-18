from typing import Any

from shared.diagnostics import Command, command
from shared.subsystem import (
    Level,
    LinkState,
    Option,
    Result,
    Table,
    boolean,
    choice,
    group,
    integer,
)


def drives(sub: Any) -> tuple[Option, ...]:
    if sub is None or sub.link_state() is not LinkState.UP:
        return ()
    return tuple(Option(name, name) for name in sub.board().drives)


DRIVE = choice("drive", drives, hint="Which demo drive.")


@command()
def read_temperature(demo: Any, values: dict[str, Any]) -> Result:
    """Read the board's temperature."""
    celsius = demo.board().temperature()
    return Result(
        level=Level.OK,
        summary=f"{celsius} C",
        fields=(("temperature", f"{celsius} C"),),
    )


@command(inputs=(DRIVE, boolean("on")), hazard="energises or releases a demo drive")
def enable(demo: Any, values: dict[str, Any]) -> Result:
    """Enable or disable one drive.

    Left enabled until something disables it, which is what a command is for.
    """
    drive = demo.board().drive(values["drive"])
    drive.enabled = bool(values["on"])
    said = "enabled" if drive.enabled else "disabled"
    return Result(level=Level.OK, summary=f"{values['drive']} {said}")


@command(
    inputs=(DRIVE, integer("velocity", min=-20_000, max=20_000)),
    hazard="turns a demo drive",
)
def set_velocity(demo: Any, values: dict[str, Any]) -> Result:
    """Set one drive turning."""
    drive = demo.board().drive(values["drive"])
    if not drive.enabled:
        return Result(level=Level.WARN, summary=f"{values['drive']} is not enabled")
    drive.velocity = int(values["velocity"])
    return Result(level=Level.OK, summary=f"{values['drive']} at {drive.velocity}")


@command(inputs=(DRIVE, boolean("jammed")), hazard="makes a demo drive ignore stop")
def jam(demo: Any, values: dict[str, Any]) -> Result:
    """Jam or free one drive.

    A jammed drive does not stop when told to, so Stop and the Hazardous test's
    end step report it.
    """
    drive = demo.board().drive(values["drive"])
    drive.jammed = bool(values["jammed"])
    return Result(
        level=Level.WARN if drive.jammed else Level.OK,
        summary=f"{values['drive']} {'jammed' if drive.jammed else 'free'}",
    )


@command()
def raises(demo: Any, values: dict[str, Any]) -> Result:
    """Raise an exception.

    A command that raises replies with an error rather than crashing anything.
    """
    raise OSError("the demo board raised this, as asked")


@command(
    inputs=(
        group("rows", columns=(DRIVE, integer("velocity", min=-20_000, max=20_000))),
    ),
)
def echo_rows(demo: Any, values: dict[str, Any]) -> Result:
    """Send back a table of rows."""
    rows = tuple((str(one["drive"]), str(one["velocity"])) for one in values["rows"])
    return Result(
        level=Level.OK,
        summary=f"{len(rows)} row(s)",
        table=Table(head=("drive", "velocity"), rows=rows),
    )


COMMANDS: tuple[Command, ...] = (
    read_temperature,
    enable,
    set_velocity,
    jam,
    raises,
    echo_rows,
)
