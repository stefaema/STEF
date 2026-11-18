"""Is this body fit to shoot, and will it take an instruction and give it back."""

from typing import TYPE_CHECKING, Any

from portable.ccapi import Setting, ThermalRestriction
from shared.diagnostics import Failed, Test, end, step
from shared.subsystem import Level, Result, Table

if TYPE_CHECKING:
    from capture.subsystem import Capture

# The thermal states that stop a scan rather than slow one down.
REFUSING = frozenset(
    {
        ThermalRestriction.STILLS_REFUSED,
        ThermalRestriction.LIVE_VIEW_REFUSED,
        ThermalRestriction.LIVE_VIEW_REFUSED_MOVIE_RESTRICTED,
    }
)

# What a scan reads and writes constantly, so what is worth proving it can.
EXERCISED = (Setting.ISO, Setting.TV)


class Health(Test[Any]):
    """Ask the two questions that decide whether a reel can be started at all.

    Both are cheap reads and neither moves anything, so this is what to run
    first and what to run again when something later behaves strangely. A body
    that is hot or nearly flat fails in ways that look like network faults.
    """

    sub: Capture

    @step("Battery", continue_on_failure=True)
    def battery(self) -> None:
        battery = self.sub.camera().status.battery()
        flat = not battery.present
        shown = Result(
            level=Level.ERROR if flat else Level.OK,
            summary=f"power is {battery.source.value}",
            fields=(
                ("name", battery.name or "--"),
                ("source", battery.source.value),
                ("charge", battery.power.value),
            ),
        )
        said = f"{battery.source.value}, {battery.power.value}"
        if flat:
            raise Failed(said, shown)
        self.report(said, shown)

    @step("Heat")
    def heat(self) -> None:
        heat = self.sub.camera().status.thermal()
        refusing = heat in REFUSING
        warm = heat is not ThermalRestriction.NORMAL
        summary = (
            "the body is refusing to shoot until it cools"
            if refusing
            else f"the body is warm: {heat.name}"
            if warm
            else "the body is at normal temperature"
        )
        shown = Result(
            level=Level.ERROR if refusing else Level.WARN if warm else Level.OK,
            summary=summary,
            note="nothing else here will behave until this clears"
            if refusing
            else None,
        )
        if refusing:
            raise Failed(heat.name, shown)
        said = self.warn if warm else self.report
        said(heat.name, shown)


class ReadAndWrite(Test[Any]):
    """Move ISO and shutter speed one notch and put them back where they were.

    A scan does nothing to a camera but read settings and write them, so the
    cheapest useful proof that the link works in both directions is to do
    exactly that and leave no trace. One notch, because the point is that the
    write took, not what it was set to.
    """

    sub: Capture

    @step("Read")
    def read(self) -> None:
        found = self.sub.camera()
        self.started: dict[Setting, str] = {}
        self.choices: dict[Setting, tuple[str, ...]] = {}
        for setting in EXERCISED:
            if not found.settings.offers(setting):
                continue
            reading = found.settings.get(setting)
            self.started[setting] = str(reading.value)
            self.choices[setting] = tuple(str(one) for one in reading.allowed)
        if not self.started:
            raise Failed("this body offers neither ISO nor shutter speed")
        self.report(
            ", ".join(f"{one.name} {self.started[one]}" for one in self.started)
        )

    @step("Write", hazard="moves ISO and shutter speed one notch")
    def write(self) -> None:
        found = self.sub.camera()
        rows: list[tuple[str, ...]] = []
        refused = 0
        for setting, was in self.started.items():
            wanted = _next_to(was, self.choices[setting])
            if wanted is None:
                rows.append((setting.name, was, "--", was, "nothing to move to"))
                continue
            found.settings.set(setting, wanted)
            now = str(found.settings.get(setting).value)
            took = now == wanted
            refused += not took
            rows.append((setting.name, was, wanted, now, "took" if took else "refused"))
        said = self.warn if refused else self.report
        said(
            f"{len(rows) - refused} of {len(rows)} took",
            Result(
                level=Level.WARN if refused else Level.OK,
                summary=f"{len(rows) - refused} of {len(rows)} write(s) took",
                table=Table(
                    head=("Setting", "Was", "Asked", "Read back", "Verdict"),
                    rows=tuple(rows),
                ),
            ),
        )

    @end("Put it back")
    def put_it_back(self) -> None:
        started = getattr(self, "started", {})
        if not started:
            self.report("nothing was read, so nothing to put back")
            return
        found = self.sub.camera()
        stuck = []
        for setting, was in started.items():
            found.settings.set(setting, was)
            if str(found.settings.get(setting).value) != was:
                stuck.append(setting.name)
        if stuck:
            raise Failed(
                f"{', '.join(stuck)} did not go back",
                Result(
                    level=Level.ERROR,
                    summary=f"{', '.join(stuck)} is not where this found it",
                ),
            )
        self.report("back as it was")


def _next_to(value: str, allowed: tuple[str, ...]) -> str | None:
    """Return a neighbour of `value`, preferring the one after it.

    Either direction proves the same thing, so the one that exists wins. A
    setting with nowhere to move is not a failure, it is a body with one
    option, and the caller says so rather than inventing a value.
    """
    if value not in allowed or len(allowed) < 2:
        return None
    at = allowed.index(value)
    return allowed[at + 1] if at + 1 < len(allowed) else allowed[at - 1]
