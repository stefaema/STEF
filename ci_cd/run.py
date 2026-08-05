"""Repository verification. See ci_cd/README.md.

python -m ci_cd.run lint | test | integration
python -m ci_cd.run build tmc2209
python -m ci_cd.run --list
"""

import argparse
import os
import sys
from pathlib import Path

from ci_cd import actions
from ci_cd.checks import apply_fmt, check_build, check_commit_msg, check_fmt, check_test
from ci_cd.discovery import Module, discover
from ci_cd.environment import ensure_hooks, ensure_tools, staged_files, tracked_files
from ci_cd.paths import ROOT
from ci_cd.ui import DIM, OFF


def list_modules(mods: list[Module]) -> int:
    for m in mods:
        bits = []
        if m.idf_project:
            bits.append("idf")
        bits += [f"ctest:{d.relative_to(m.path)}" for d in m.ctest_dirs]
        if m.python_pkg:
            bits.append("python")
        print(f"  {m.name:<14} {' '.join(bits) or DIM + 'empty' + OFF}")
    return 0


def one_module(name: str, mods: list[Module]) -> Module | None:
    m = next((m for m in mods if m.name == name), None)
    if m is None:
        print(f"no module named {name!r}", file=sys.stderr)
    return m


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m ci_cd.run",
        description=__doc__.strip().splitlines()[0] if __doc__ else None,
    )
    ap.add_argument(
        "--list", action="store_true", help="show discovered modules and exit"
    )
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("lint", help="format and lint")
    p.add_argument("--staged", action="store_true", help="only what is in the index")

    p = sub.add_parser("fmt", help="format check only")
    p.add_argument("--staged", action="store_true", help="only what is in the index")
    p.add_argument("--fix", action="store_true", help="rewrite rather than report")

    p = sub.add_parser("test", help="build and unit tests, every module")
    p.add_argument("module", nargs="?", help="restrict to one module, tests only")

    sub.add_parser(
        "integration", help="test, plus what only makes sense across modules"
    )

    p = sub.add_parser("build", help="build every module")
    p.add_argument("module", nargs="?", help="restrict to one module")

    p = sub.add_parser("commit-msg", help="check one commit message file")
    p.add_argument("file")

    p = sub.add_parser("verify-for", help="run what a destination branch demands")
    p.add_argument("destination", nargs="*", help="branch names or refs/heads/... refs")

    return ap


def main() -> int:
    ap = parser()
    a = ap.parse_args()
    mods = discover()

    if a.list:
        return list_modules(mods)

    if a.cmd is None:
        ap.print_help()
        return 0

    if a.cmd == "lint":
        return 0 if actions.lint(staged=a.staged) else 1

    if a.cmd == "fmt":
        files = staged_files() if a.staged else tracked_files()
        run_fmt = apply_fmt if a.fix else check_fmt
        return 0 if run_fmt(files) else 1

    if a.cmd == "integration":
        return 0 if actions.integration(mods) else 1

    if a.cmd == "commit-msg":
        return 0 if check_commit_msg(Path(a.file)) else 1

    if a.cmd == "verify-for":
        action = actions.required_for(a.destination)
        if action is None:
            where = ", ".join(a.destination) or "nowhere"
            print(f"{where}: not an integration branch, nothing to check")
            return 0
        return 0 if actions.run(action, mods) else 1

    if a.cmd == "test":
        if a.module is None:
            return 0 if actions.test(mods) else 1
        m = one_module(a.module, mods)
        return 2 if m is None else (0 if check_test(m) else 1)

    if a.cmd == "build":
        if a.module is None:
            ok = True
            for m in mods:
                ok &= check_build(m)
            return 0 if ok else 1
        m = one_module(a.module, mods)
        return 2 if m is None else (0 if check_build(m) else 1)

    ap.print_help()
    return 2


if __name__ == "__main__":
    os.chdir(ROOT)
    ensure_hooks()
    ensure_tools()
    sys.exit(main())
