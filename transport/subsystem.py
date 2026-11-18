from typing import Any

from shared import fw_api
from shared.diagnostics import Diagnosable
from shared.subsystem import Level, Linked, LinkState, Readiness, Result
from transport import fw
from transport.bench import calls, link, prelink, setup, spin
from transport.transport import opened, text


class Transport(Linked[str], Diagnosable):
    safe_state = "every drive halted, VACTUAL 0, power stage off"
    target = link.PORT
    tests = (
        prelink.VerifyPort,
        prelink.FlashBoard,
        setup.BaselineBringup,
        spin.OneTurn,
        spin.VelocityTurn,
    )
    commands = calls.COMMANDS

    def firmware(self) -> fw.link.FirmwareLink:
        return self.handle()

    def probe(self, target: str) -> Readiness:
        return link.can_connect(target)

    def _open(self, target: str) -> fw.link.FirmwareLink:
        return opened(target, on_lost=self.announce_link_lost)

    def _close(self, handle: fw.link.FirmwareLink) -> None:
        handle.close()

    def _alive(self, handle: fw.link.FirmwareLink) -> bool:
        return handle.alive

    def stop(self) -> None:
        board = self.firmware()
        raw = board.raw
        failures: list[str] = []
        for idx, entry in enumerate(board.sys.devices().devs):
            name = text(entry.name) or f"drive {idx}"
            for undo in (_halted, _still, _released):
                try:
                    undo(raw, idx)
                except Exception as exc:
                    failures.append(f"{name}: {type(exc).__name__}: {exc}")
        if failures:
            raise RuntimeError("; ".join(failures))

    def facts(self) -> Result | None:
        if self.link_state() is not LinkState.UP:
            return None
        board = self.firmware()
        version = board.sys.version()
        state = board.sys.state()
        drives = [text(entry.name) for entry in board.sys.devices().devs]
        tripped = state.mode is fw_api.RpcMode.TRIPPED
        mode = state.mode.name.removeprefix("RPC_MODE_").lower()
        reason = state.trip_reason.name.removeprefix("RPC_TRIP_").lower()
        summary = f"{text(version.backend)} {text(version.version)}"
        if tripped:
            summary = f"tripped: {reason}"
        return Result(
            level=Level.WARN if tripped else Level.OK,
            summary=summary,
            fields=(
                ("backend", text(version.backend)),
                ("version", text(version.version)),
                ("idf", text(version.idf)),
                ("drives", ", ".join(drives) or "none"),
                ("mode", mode),
                ("trip", f"{reason}, detail {state.trip_detail}"),
            ),
        )


def _halted(raw: Any, idx: int) -> None:
    try:
        raw.halt(idx=idx, immediate=False)
    except Exception:
        raw.halt(idx=idx, immediate=True)


def _still(raw: Any, idx: int) -> None:
    raw.set_velocity(idx=idx, velocity=0)


def _released(raw: Any, idx: int) -> None:
    raw.enable(idx=idx, on=False)
    if raw.is_enabled(idx=idx).on:
        raise RuntimeError("the power stage still reports enabled")
