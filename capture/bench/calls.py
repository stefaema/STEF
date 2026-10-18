"""Every camera setting, declared as a routine, without writing any of them out.

The protocol gives each setting the same shape: a value, and the list of values
this body will accept for it. That list is only correct once the setting is
fixed, so the value control has to be built per setting rather than shared
between them, which is what makes a loop the way to declare them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from portable.ccapi import Setting
from shared.diagnostics import Command
from shared.subsystem import (
    READY,
    Level,
    LinkState,
    Option,
    Readiness,
    Result,
    blocked,
    choice,
)

GROUP = "calls"

# Written before a scan and never during one, so getting these wrong costs a
# whole reel rather than a frame.
HAZARDOUS = {
    Setting.ISO,
    Setting.AV,
    Setting.TV,
    Setting.STILLIMAGEQUALITY,
    Setting.SHUTTERMODE,
    Setting.DRIVE,
    Setting.AFOPERATION,
    Setting.SHOOTINGMODE,
}


def allowed_for(setting: Setting) -> Callable[[Any], tuple[Option, ...]]:
    """Return what fills this setting's value control, asked when it is drawn.

    Asked and not declared: what a body accepts depends on the mode it is in,
    and a list captured at import would be the list some other camera had.
    """

    def options(sub: Any) -> tuple[Option, ...]:
        if sub is None or sub.link_state() is not LinkState.UP:
            return ()
        try:
            return tuple(
                Option(one, str(one)) for one in sub.camera().settings.allowed(setting)
            )
        except Exception:  # noqa: BLE001
            return ()

    return options


def offered(setting: Setting) -> Callable[[Any], Readiness]:
    def can_run(sub: Any) -> Readiness:
        if not sub.camera().settings.offers(setting):
            return blocked("this camera does not offer it")
        return READY

    return can_run


def reader(setting: Setting) -> Callable[[Any, dict[str, Any]], Result]:
    """Return the routine that reads one setting and says what it will accept."""

    def run(sub: Any, values: dict[str, Any]) -> Result:
        found = sub.camera().settings.get(setting)
        return Result(
            level=Level.OK,
            summary=f"{setting} is {found.value!r}",
            fields=(
                ("value", str(found.value)),
                ("writable", "yes" if found.writable else "no"),
                ("allowed", ", ".join(str(one) for one in found.allowed) or "-"),
            ),
        )

    return run


def writer(setting: Setting) -> Callable[[Any, dict[str, Any]], Result]:
    def run(sub: Any, values: dict[str, Any]) -> Result:
        settings = sub.camera().settings
        asked = values.get("value")
        settings.set(setting, asked)
        now = settings.get(setting).value
        took = now == asked
        return Result(
            level=Level.OK if took else Level.WARN,
            summary=f"asked {asked!r}, got {now!r}",
            note=None if took else "the camera did not take it, and said nothing",
        )

    return run


def declared() -> tuple[Command, ...]:
    """Declare a read and a write command for every setting the protocol names."""
    made = []
    for setting in Setting:
        name = setting.name.lower()
        made.append(
            Command(
                group=GROUP,
                name=f"read_{name}",
                title=f"Read {name}",
                description=f"Read {setting} and what this body will accept for it.",
                call=reader(setting),
                can_run=offered(setting),
            )
        )
        made.append(
            Command(
                group=GROUP,
                name=f"write_{name}",
                title=f"Write {name}",
                description=f"Write {setting} and read back what the body took.",
                call=writer(setting),
                inputs=(choice("value", allowed_for(setting)),),
                hazard=f"changes {setting}" if setting in HAZARDOUS else None,
                can_run=offered(setting),
            )
        )
    return tuple(made)


COMMANDS = declared()
