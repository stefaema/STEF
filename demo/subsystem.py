import time

from demo.bench import asking, calls, link, outcomes, port, running
from demo.board import DIES, DIES_AFTER_S, FAILS_TO_OPEN, REFUSES, Board
from shared.diagnostics import Diagnosable
from shared.subsystem import READY, Level, Linked, LinkState, Readiness, Result, blocked


class Demo(Linked[str], Diagnosable):
    safe_state = "every demo drive disabled and standing still"
    target = link.TARGET
    tests = (
        port.NeedsThePort,
        outcomes.Passes,
        outcomes.Warns,
        outcomes.FailsEarly,
        outcomes.CarriesOn,
        outcomes.OutOfLimits,
        outcomes.FinishesEarly,
        outcomes.SkipsOne,
        outcomes.EndsBadly,
        outcomes.Guarded,
        asking.Asks,
        running.RunsLong,
        running.Hazardous,
        running.EndsSlowly,
    )
    commands = calls.COMMANDS

    def board(self) -> Board:
        return self.handle().answering()

    def probe(self, target: str) -> Readiness:
        if target == REFUSES:
            return blocked("the demo board refuses to connect, as asked")
        return READY

    def _open(self, target: str) -> Board:
        time.sleep(link.PACE_S)
        if target == FAILS_TO_OPEN:
            raise OSError("the demo board would not open, as asked")
        return Board(dies_after=DIES_AFTER_S if target == DIES else None)

    def _close(self, handle: Board) -> None:
        handle.close()

    def _alive(self, handle: Board) -> bool:
        return handle.alive

    def stop(self) -> None:
        board = self.board()
        stuck = []
        for name, drive in board.drives.items():
            if drive.jammed:
                stuck.append(name)
                continue
            drive.velocity = 0
            drive.enabled = False
        if stuck:
            raise RuntimeError(
                f"{', '.join(stuck)}: jammed, so it would not confirm it stopped"
            )

    def facts(self) -> Result | None:
        if self.link_state() is not LinkState.UP:
            return None
        board = self.board()
        return Result(
            level=Level.OK,
            summary="a demo board, with nothing behind it",
            fields=(
                ("drives", ", ".join(board.drives)),
                ("temperature", f"{board.temperature()} C"),
            ),
        )
