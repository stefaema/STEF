"""Finding a camera, and asking whether it will serve us, while nothing holds it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from capture import capture, probe
from shared.diagnostics import Failed, Needs, Test, step
from shared.subsystem import Level, Result, Table

if TYPE_CHECKING:
    from capture.subsystem import Capture

HEAD = ("Address", "Model", "Serial", "In use")


class Search(Test[Any]):
    """Search the network.

    Asks every camera on this subnet to describe itself, out of every interface
    this host has. Multicast does not cross a router and an access point may
    drop it, so silence here means nothing was heard rather than nothing is
    there, and the result says which of those it was.
    """

    sub: Capture
    needs = Needs.DOWN

    @step("Search")
    def search(self) -> None:
        swept = probe.sweep()
        if not swept:
            pinned = capture.pinned_host()
            note = (
                f"the configured address {pinned} is still worth trying"
                if pinned
                else "no address is configured either, so there is nothing to connect to"
            )
            self.warn(
                swept.sentence,
                Result(level=Level.WARN, summary=swept.sentence, note=note),
            )
            return
        rows = tuple(
            (
                one.address,
                one.model or "?",
                one.serial or "?",
                "yes" if one.held else "no",
            )
            for one in swept.found
        )
        self.report(
            f"{len(swept.found)} answered",
            Result(
                level=Level.OK,
                summary=swept.sentence,
                table=Table(head=HEAD, rows=rows),
            ),
        )


class WhetherItServes(Test[Any]):
    """Ask whether the configured camera will serve us.

    Connects far enough to read the manifest and no further, then lets go. This
    is the same question a blocked Connect button answers, asked on purpose.
    """

    sub: Capture
    needs = Needs.DOWN

    @step("Ask")
    def ask_it(self) -> None:
        host = capture.settle(capture.AUTO)
        verdict = probe.identify(capture.configured(host))
        if verdict:
            self.report(
                verdict.sentence, Result(level=Level.OK, summary=verdict.sentence)
            )
            return
        raise Failed(
            verdict.sentence, Result(level=Level.ERROR, summary=verdict.sentence)
        )
