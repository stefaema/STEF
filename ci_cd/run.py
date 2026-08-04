#!/usr/bin/env python3
"""Repository verification. See ci_cd/README.md.

ci_cd/run.py gate 1 | gate 2 | gate 3
ci_cd/run.py build tmc2209
ci_cd/run.py --list
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".ci-build"

EXTRA_SCOPES = {"docs", "meta", "repo"}

GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


# ── What a module is ─────────────────────────────────────────────────────────


@dataclass
class Module:
    name: str
    path: Path
    idf_project: Path | None
    ctest_dirs: list[Path]
    python_pkg: bool
    cffi_build: Path | None

    @property
    def empty(self) -> bool:
        return not (self.idf_project or self.ctest_dirs or self.python_pkg)


def discover() -> list[Module]:
    mods = []
    for flake in sorted(ROOT.glob("*/flake.nix")):
        path = flake.parent
        idf = None
        for candidate in (path / "src", path):
            cml = candidate / "CMakeLists.txt"
            if cml.exists() and "project.cmake" in cml.read_text():
                idf = candidate
                break
        ctest = [
            d.parent
            for d in sorted(path.glob("*/CMakeLists.txt"))
            if d.parent.name in ("test", "tests")
        ]
        ctest += [d.parent for d in sorted(path.glob("test/*/CMakeLists.txt"))]
        mods.append(
            Module(
                name=path.name,
                path=path,
                idf_project=idf,
                ctest_dirs=sorted(set(ctest)),
                python_pkg=(path / "pyproject.toml").exists(),
                cffi_build=next(iter(sorted(path.glob("src/*/_build.py"))), None),
            )
        )
    return mods


def module_of(rel: Path, mods: list[Module]) -> Module | None:
    top = rel.parts[0] if rel.parts else ""
    return next((m for m in mods if m.name == top), None)


# ── Running things ───────────────────────────────────────────────────────────


TOOLS = ("ruff", "clang-tidy")


def ensure_tools() -> None:
    import shutil

    if os.environ.get("STEF_CI_SHELL") or all(shutil.which(t) for t in TOOLS):
        return
    if not shutil.which("nix"):
        print(
            f"{RED}nix not found, and the pinned tools are not on PATH{OFF}",
            file=sys.stderr,
        )
        sys.exit(2)
    os.environ["STEF_CI_SHELL"] = "1"
    os.execvp(
        "nix",
        [
            "nix",
            "develop",
            str(ROOT / "ci_cd"),
            "--command",
            sys.executable,
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ],
    )


HOOKS_PATH = "ci_cd/hooks"


def ensure_hooks() -> None:
    if not (ROOT / ".git").exists():
        return

    def git(*args: str) -> str:
        p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return p.stdout.strip()

    wanted = {"core.hooksPath": HOOKS_PATH, "merge.ff": "false"}
    changed = [k for k, v in wanted.items() if git("config", k) != v]
    for key in changed:
        git("config", key, wanted[key])
    if changed:
        print(f"{DIM}git config: {', '.join(changed)}{OFF}", file=sys.stderr)


def sh(cmd: list[str], cwd: Path = ROOT) -> int:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"{RED}{cmd[0]} not found{OFF}", file=sys.stderr)
        return 127
    if p.returncode != 0:
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
    return p.returncode


def in_shell(module: Module, script: str) -> int:
    return sh(["nix", "develop", f"./{module.name}", "--command", "bash", "-c", script])


def staged_files() -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout
    return [Path(p) for p in out.split() if (ROOT / p).exists()]


def report(label: str, ok: bool, note: str = "") -> bool:
    mark = f"{GREEN}ok{OFF}" if ok else f"{RED}FAIL{OFF}"
    tail = f" {DIM}{note}{OFF}" if note else ""
    print(f"  {mark:<16} {label}{tail}")
    return ok


def skip(label: str, why: str) -> bool:
    print(f"  {YELLOW}skip{OFF}{'':<12} {label} {DIM}{why}{OFF}")
    return True


# ── The checks ───────────────────────────────────────────────────────────────


def check_fmt(files: list[Path]) -> bool:
    py = [f for f in files if f.suffix == ".py"]
    if not py:
        return skip("fmt", "no python files staged")
    rc = sh(["ruff", "format", "--check", *[str(f) for f in py]])
    return report("fmt", rc == 0, f"{len(py)} python files")


GCC_ONLY = {
    "-mlongcalls",
    "-mtext-section-literals",
    "-mdisable-hardware-atomics",
    "-fno-tree-switch-conversion",
    "-fno-inline-small-functions",
    "-fno-inline-functions-called-once",
    "-fstrict-volatile-bitfields",
    "-fno-shrink-wrap",
}


def tidy_db(src: Path) -> Path | None:
    import functools
    import json
    import shlex

    if not (src / "compile_commands.json").exists():
        return None

    @functools.lru_cache(maxsize=None)
    def system_includes(driver: str) -> tuple[str, ...]:
        probe = subprocess.run(
            [driver, "-xc", "-E", "-v", "-"], input="", capture_output=True, text=True
        )
        dirs, collecting = [], False
        for line in probe.stderr.splitlines():
            if line.startswith("#include <...>"):
                collecting = True
            elif line.startswith("End of search list"):
                break
            elif collecting:
                dirs.append(os.path.normpath(line.strip()))
        if not dirs:
            return ()
        return ("-nostdlibinc", *[a for d in dirs for a in ("-isystem", d)])

    out = []
    for e in json.loads((src / "compile_commands.json").read_text()):
        if not e["file"].startswith(str(ROOT)) or not e["file"].endswith(
            (".c", ".cpp")
        ):
            continue
        argv = shlex.split(e["command"]) if "command" in e else list(e["arguments"])
        argv = [
            a
            for a in argv
            if a not in GCC_ONLY and not a.startswith("-fmacro-prefix-map=")
        ]
        argv += [
            "-Wno-unknown-attributes",
            "-Wno-ignored-attributes",
            *system_includes(argv[0]),
        ]
        e.pop("arguments", None)
        e["command"] = shlex.join(argv)
        out.append(e)

    dst = BUILD / "tidy"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "compile_commands.json").write_text(json.dumps(out, indent=2))
    return dst


def check_lint(files: list[Path], mods: list[Module]) -> bool:
    ok = True
    py = [f for f in files if f.suffix == ".py"]
    if py:
        ok &= report("lint (python)", sh(["ruff", "check", *[str(f) for f in py]]) == 0)

    c = [f for f in files if f.suffix in (".c", ".h")]
    if not c:
        return ok and skip("lint (c)", "no C files staged")

    db = tidy_db(ROOT / "firmware" / "src" / "build")
    if db is None:
        return ok and skip("lint (c)", "no compile database, run gate 2 first")

    sources = [f for f in c if f.suffix == ".c"]
    if not sources:
        return ok and skip("lint (c)", f"{len(c)} headers, checked via their includers")

    rc = sh(
        [
            "clang-tidy",
            "-p",
            str(db),
            "--quiet",
            "--warnings-as-errors=*",
            *[str(f) for f in sources],
        ]
    )
    return ok and report("lint (c)", rc == 0, f"{len(sources)} files")


def check_commit_msg(path: Path) -> bool:
    msg = path.read_text().strip()
    first = next((ln for ln in msg.splitlines() if ln and not ln.startswith("#")), "")
    scopes = {m.name for m in discover()} | EXTRA_SCOPES

    m = re.match(r"^([a-z0-9_-]+): (.+)$", first)
    if not m:
        return report("commit message", False, f"want 'scope: subject', got {first!r}")
    if m.group(1) not in scopes:
        return report(
            "commit message",
            False,
            f"unknown scope {m.group(1)!r}, want one of {', '.join(sorted(scopes))}",
        )
    if len(first) > 72:
        return report(
            "commit message", False, f"subject is {len(first)} chars, limit 72"
        )
    return report("commit message", True, first)


def check_build(m: Module) -> bool:
    if m.empty:
        return skip(f"build {m.name}", "nothing to build yet")
    ok = True
    if m.idf_project:
        ok &= report(
            f"build {m.name}",
            in_shell(m, f"cd {m.idf_project} && idf.py build > /dev/null") == 0,
            "idf.py",
        )
    for d in m.ctest_dirs:
        out = BUILD / m.name / d.name
        rc = in_shell(
            m,
            f"cmake -S {d} -B {out} -G Ninja > /dev/null && cmake --build {out} > /dev/null",
        )
        ok &= report(f"build {m.name}/{d.relative_to(m.path)}", rc == 0, "cmake")
    # Before the python check, not after: this module's tests import an
    # extension compiled from another module's C, so it has to exist first.
    if m.cffi_build:
        ok &= report(
            f"build {m.name}", in_shell(m, f"python {m.cffi_build}") == 0, "cffi"
        )
    if m.python_pkg:
        ok &= report(
            f"build {m.name}", in_shell(m, "python -c 'import sys'") == 0, "python"
        )
    return ok


def check_test(m: Module) -> bool:
    if not m.ctest_dirs and not m.python_pkg:
        return skip(f"test {m.name}", "no tests yet")
    ok = True
    for d in m.ctest_dirs:
        out = BUILD / m.name / d.name
        rc = in_shell(m, f"ctest --test-dir {out} --output-on-failure")
        ok &= report(f"test {m.name}/{d.relative_to(m.path)}", rc == 0, "ctest")
    if m.python_pkg:
        ok &= report(
            f"test {m.name}", in_shell(m, f"pytest {m.path} -q") == 0, "pytest"
        )
    return ok


# ── Gates ────────────────────────────────────────────────────────────────────


def gate1(mods: list[Module]) -> bool:
    files = staged_files()
    print(f"{DIM}gate 1: {len(files)} staged files{OFF}")
    if not files:
        return skip("gate 1", "nothing staged")
    return check_fmt(files) & check_lint(files, mods)


def gate2(mods: list[Module]) -> bool:
    print(f"{DIM}gate 2: build and unit tests, every module{OFF}")
    ok = True
    for m in mods:
        ok &= check_build(m)
        ok &= check_test(m)
    return ok


def gate3(mods: list[Module]) -> bool:
    ok = gate2(mods)
    print(f"{DIM}gate 3: across modules{OFF}")
    ok &= skip("cross-module", "needs a second subsystem")
    ok &= skip("derived docs", "needs the doc generator")
    return ok


GATES = {"1": gate1, "2": gate2, "3": gate3}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "what",
        nargs="?",
        default="gate",
        choices=["gate", "build", "test", "lint", "fmt", "commit-msg"],
    )
    ap.add_argument(
        "arg", nargs="?", help="gate number, module name, or commit message file"
    )
    ap.add_argument(
        "--list", action="store_true", help="show discovered modules and exit"
    )
    a = ap.parse_args()

    mods = discover()
    if a.list:
        for m in mods:
            bits = []
            if m.idf_project:
                bits.append("idf")
            bits += [f"ctest:{d.relative_to(m.path)}" for d in m.ctest_dirs]
            if m.cffi_build:
                bits.append("cffi")
            if m.python_pkg:
                bits.append("python")
            print(f"  {m.name:<14} {' '.join(bits) or DIM + 'empty' + OFF}")
        return 0

    if a.what == "commit-msg":
        return 0 if check_commit_msg(Path(a.arg)) else 1

    if a.what == "gate":
        gate = GATES.get(a.arg or "1")
        if gate is None:
            print(f"unknown gate {a.arg!r}, want 1, 2 or 3", file=sys.stderr)
            return 2
        return 0 if gate(mods) else 1

    chosen = [m for m in mods if m.name == a.arg] if a.arg else mods
    if not chosen:
        print(f"no module named {a.arg!r}", file=sys.stderr)
        return 2

    fn = {"build": check_build, "test": check_test}.get(a.what)
    if fn:
        return 0 if all(fn(m) for m in chosen) else 1

    files = staged_files()
    ok = check_fmt(files) if a.what == "fmt" else check_lint(files, mods)
    return 0 if ok else 1


if __name__ == "__main__":
    os.chdir(ROOT)
    ensure_hooks()
    ensure_tools()
    sys.exit(main())
