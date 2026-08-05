from ci_cd.checks import (
    check_build,
    check_fmt,
    check_generated,
    check_lint,
    check_test,
    check_types,
)
from ci_cd.discovery import Module, discover
from ci_cd.environment import staged_files, tracked_files
from ci_cd.ui import heading, skip

ORDER = ("lint", "test", "integration")

BRANCH_ACTION = {"main": "integration", "develop": "test"}


def lint(staged: bool = False) -> bool:
    files = staged_files() if staged else tracked_files()
    where = "staged" if staged else "tracked"
    heading(f"lint: {len(files)} {where} files")
    if not files:
        return skip("lint", f"no {where} files")
    return check_fmt(files) & check_lint(files) & check_types(discover())


def test(mods: list[Module]) -> bool:
    ok = lint()
    heading("test: build and unit tests, every module")
    for m in mods:
        ok &= check_build(m)
        ok &= check_test(m)
    return ok


def integration(mods: list[Module]) -> bool:
    ok = test(mods)
    heading("integration: across modules")
    ok &= check_generated(mods)
    ok &= skip("cross-module", "needs a second subsystem")
    ok &= skip("derived docs", "needs the doc generator")
    return ok


def run(name: str, mods: list[Module]) -> bool:
    if name == "lint":
        return lint()
    if name == "test":
        return test(mods)
    if name == "integration":
        return integration(mods)
    raise ValueError(f"unknown action {name!r}")


def required_for(names: list[str]) -> str | None:
    named = [
        s
        for n in names
        if (s := BRANCH_ACTION.get(n.removeprefix("refs/heads/"))) is not None
    ]
    return max(named, key=ORDER.index, default=None)
