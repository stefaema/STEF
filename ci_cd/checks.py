import re
from pathlib import Path

import tidy_db
from discovery import Module, discover
from environment import in_shell, sh
from paths import CICD_BUILD, ROOT
from ui import hint, report, skip

EXTRA_SCOPES = {"docs", "meta", "repo"}
PYTEST_NO_TESTS = 5


def check_fmt(files: list[Path]) -> bool:
    ok = True

    py = [f for f in files if f.suffix == ".py"]
    if py:
        rc = sh(["ruff", "format", "--check", *[str(f) for f in py]])
        ok &= report("fmt (python)", rc == 0, f"{len(py)} files")
    else:
        skip("fmt (python)", "no python files")

    c = [f for f in files if f.suffix in (".c", ".h")]
    if c:
        rc = sh(["clang-format", "--dry-run", "-Werror", *[str(f) for f in c]])
        ok &= report("fmt (c)", rc == 0, f"{len(c)} files")
    else:
        skip("fmt (c)", "no C files")

    if not ok:
        hint("ci_cd/run.py fmt --fix")
    return ok


def apply_fmt(files: list[Path]) -> bool:
    ok = True

    py = [f for f in files if f.suffix == ".py"]
    if py:
        names = [str(f) for f in py]
        # ruff format does not order imports; I is a lint rule, so it needs its
        # own pass. Selected alone, to leave every other lint finding to lint.
        rc = sh(["ruff", "format", *names]) or sh(
            ["ruff", "check", "--fix", "--select", "I", *names]
        )
        ok &= report("fmt (python)", rc == 0, f"{len(py)} files")
    else:
        skip("fmt (python)", "no python files")

    c = [f for f in files if f.suffix in (".c", ".h")]
    if c:
        rc = sh(["clang-format", "-i", *[str(f) for f in c]])
        ok &= report("fmt (c)", rc == 0, f"{len(c)} files")
    else:
        skip("fmt (c)", "no C files")

    return ok


def check_lint(files: list[Path]) -> bool:
    ok = True
    py = [f for f in files if f.suffix == ".py"]
    if py:
        ok &= report("lint (python)", sh(["ruff", "check", *[str(f) for f in py]]) == 0)

    c = [f for f in files if f.suffix in (".c", ".h")]
    if not c:
        return ok and skip("lint (c)", "no C files")

    sources = [f for f in c if f.suffix == ".c"]
    if not sources:
        return ok and skip("lint (c)", f"{len(c)} headers, checked via their includers")

    built = tidy_db.rewritten_for_clang(tidy_db.sources())
    if built is None:
        return ok and skip("lint (c)", "no compile database, run test first")
    db, covered = built

    known = [f for f in sources if str((ROOT / f).resolve()) in covered]
    unbuilt = len(sources) - len(known)
    if not known:
        return ok and skip(
            "lint (c)", f"{unbuilt} files in no compile database, run test first"
        )

    rc = sh(
        [
            "clang-tidy",
            "-p",
            str(db),
            "--quiet",
            "--warnings-as-errors=*",
            *[str(f) for f in known],
        ]
    )
    note = f"{len(known)} files"
    if unbuilt:
        note += f", {unbuilt} skipped for want of a compile database"
    return ok and report("lint (c)", rc == 0, note)


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
        out = CICD_BUILD / m.name / d.name
        rc = in_shell(
            m,
            f"cmake -S {d} -B {out} -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON > /dev/null"
            f" && cmake --build {out} > /dev/null",
        )
        ok &= report(f"build {m.name}/{d.relative_to(m.path)}", rc == 0, "cmake")
    if m.python_pkg:
        ok &= report(
            f"build {m.name}", in_shell(m, "python -c 'import sys'") == 0, "python"
        )
    return ok


def check_test(m: Module) -> bool:
    if not m.ctest_dirs and not m.python_pkg:
        return skip(f"test {m.name}", "no tests found")
    ok = True
    for d in m.ctest_dirs:
        out = CICD_BUILD / m.name / d.name
        rc = in_shell(m, f"ctest --test-dir {out} --output-on-failure")
        ok &= report(f"test {m.name}/{d.relative_to(m.path)}", rc == 0, "ctest")
    if m.python_pkg:
        rc = in_shell(m, f"pytest {m.path} -q", quiet_on=(PYTEST_NO_TESTS,))
        if rc == PYTEST_NO_TESTS:
            ok &= skip(f"test {m.name}", "no tests found")
        else:
            ok &= report(f"test {m.name}", rc == 0, "pytest")
    return ok
