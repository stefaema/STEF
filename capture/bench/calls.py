"""Every camera setting, declared as a routine, without writing any of them out.

The protocol gives each setting the same shape: a value, and the list of values
this body will accept for it. That list is only correct once the setting is
fixed, so the value control has to be built per setting rather than shared
between them, which is what makes a loop the way to declare them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from capture import capture
from portable.ccapi import Setting
from shared import bench_api
from shared.bench_api import (
    CALL,
    PASSED,
    READY,
    WARNED,
    Level,
    Option,
    Readiness,
    Result,
    StepOutcome,
    blocked,
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


def allowed_for(setting: Setting) -> Callable[[], tuple[Option, ...]]:
    """Return what fills this setting's value control, asked when it is drawn.

    Asked and not declared: what a body accepts depends on the mode it is in,
    and a list captured at import would be the list some other camera had.
    """

    def options() -> tuple[Option, ...]:
        if capture.state() is not bench_api.SubsystemState.UP:
            return ()
        try:
            return tuple(
                Option(one, str(one))
                for one in capture.camera().settings.allowed(setting)
            )
        except Exception:  # noqa: BLE001
            return ()

    return options


def offered(setting: Setting) -> Callable[[], Readiness]:
    """Return the gate that hides a setting this body does not have."""

    def can_run() -> Readiness:
        if capture.state() is not bench_api.SubsystemState.UP:
            return blocked("not connected")
        if not capture.camera().settings.offers(setting):
            return blocked("this camera does not offer it")
        return READY

    return can_run


def reader(setting: Setting) -> Callable[[dict[str, Any]], Iterator[StepOutcome]]:
    """Return the routine that reads one setting and says what it will accept."""

    def run(values: dict[str, Any]) -> Iterator[StepOutcome]:
        found = capture.camera().settings.get(setting)
        yield StepOutcome(
            PASSED,
            str(found.value),
            Result(
                level=Level.OK,
                summary=f"{setting} is {found.value!r}",
                fields=(
                    ("value", str(found.value)),
                    ("writable", "yes" if found.writable else "no"),
                    ("allowed", ", ".join(str(one) for one in found.allowed) or "-"),
                ),
            ),
        )

    return run


def writer(setting: Setting) -> Callable[[dict[str, Any]], Iterator[StepOutcome]]:
    """Return the routine that writes one setting, checks it, and puts it back."""

    def run(values: dict[str, Any]) -> Iterator[StepOutcome]:
        settings = capture.camera().settings
        was = settings.get(setting)
        asked = values.get("value")
        yield StepOutcome(PASSED, f"was {was.value!r}")

        settings.set(setting, asked)
        now = settings.get(setting).value
        took = now == asked
        yield StepOutcome(
            PASSED if took else WARNED,
            f"now {now!r}",
            Result(
                level=Level.OK if took else Level.WARN,
                summary=f"asked {asked!r}, got {now!r}",
                note=None if took else "the camera did not take it, and said nothing",
            ),
        )

        settings.set(setting, was.value)
        back = settings.get(setting).value
        yield StepOutcome(
            PASSED if back == was.value else WARNED,
            f"back to {back!r}",
        )

    return run


def declare() -> int:
    """Declare a read and a write routine for every setting the protocol names."""
    made = 0
    for setting in Setting:
        name = setting.name.lower()
        bench_api.register_routine(
            module=__name__,
            group=GROUP,
            name=f"read_{name}",
            title=f"Read {name}",
            description=f"Read {setting} and what this body will accept for it.",
            category=CALL,
            run=reader(setting),
            can_run=offered(setting),
        )
        bench_api.register_routine(
            module=__name__,
            group=GROUP,
            name=f"write_{name}",
            title=f"Write {name}",
            description=(
                f"Write {setting}, read it back, and put the previous value "
                "back however it goes."
            ),
            category=CALL,
            hazardous=setting in HAZARDOUS,
            steps=["Read", "Write", "Restore"],
            inputs=[bench_api.choice("value", allowed_for(setting))],
            run=writer(setting),
            can_run=offered(setting),
        )
        made += 2
    return made


DECLARED = declare()
