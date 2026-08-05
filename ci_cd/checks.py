import re
from pathlib import Path

from ci_cd import tidy_db
from ci_cd.discovery import Module, discover
from ci_cd.environment import (
    get_module_shell_output,
    run_command,
    run_in_module_shell,
)
from ci_cd.paths import CICD_BUILD, ROOT
from ci_cd.ui import hint, report, skip

EXTRA_SCOPES = {"docs", "meta", "repo"}
PYTEST_NO_TESTS = 5


def check_fmt(files: list[Path]) -> bool:
    """Report whether the files are already formatted, pointing at the fix if not."""
    ok = True

    py = [f for f in files if f.suffix == ".py"]
    if py:
        rc = run_command(["ruff", "format", "--check", *[str(f) for f in py]])
        ok &= report("fmt (python)", rc == 0, f"{len(py)} files")
    else:
        skip("fmt (python)", "no python files")

    c = [f for f in files if f.suffix in (".c", ".h")]
    if c:
        rc = run_command(["clang-format", "--dry-run", "-Werror", *[str(f) for f in c]])
        ok &= report("fmt (c)", rc == 0, f"{len(c)} files")
    else:
        skip("fmt (c)", "no C files")

    if not ok:
        hint("python -m ci_cd.run fmt --fix")
    return ok


def apply_fmt(files: list[Path]) -> bool:
    """Rewrite the files into formatted shape, import order included."""
    ok = True

    py = [f for f in files if f.suffix == ".py"]
    if py:
        names = [str(f) for f in py]
        # ruff format leaves imports unsorted; I is the only lint rule that belongs here
        rc = run_command(["ruff", "format", *names]) or run_command(
            ["ruff", "check", "--fix", "--select", "I", *names]
        )
        ok &= report("fmt (python)", rc == 0, f"{len(py)} files")
    else:
        skip("fmt (python)", "no python files")

    c = [f for f in files if f.suffix in (".c", ".h")]
    if c:
        rc = run_command(["clang-format", "-i", *[str(f) for f in c]])
        ok &= report("fmt (c)", rc == 0, f"{len(c)} files")
    else:
        skip("fmt (c)", "no C files")

    return ok


def check_types(mods: list[Module]) -> bool:
    """Report basedpyright's verdict for each module holding Python."""
    ok = True
    checked = 0
    for m in mods:
        if not m.python_files:
            continue
        checked += 1
        interpreter = get_module_shell_output(m, "command -v python")
        if interpreter is None:
            ok &= skip(f"types {m.name}", "no python in this module's shell")
            continue
        rc = run_command(["basedpyright", "--pythonpath", interpreter, str(m.path)])
        ok &= report(f"types {m.name}", rc == 0, "basedpyright")
    return ok if checked else skip("types", "no python files")


def check_lint(files: list[Path]) -> bool:
    """Report ruff's and clang-tidy's verdicts."""
    ok = True
    py = [f for f in files if f.suffix == ".py"]
    if py:
        ok &= report(
            "lint (python)", run_command(["ruff", "check", *[str(f) for f in py]]) == 0
        )

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

    rc = run_command(
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
    """Report whether the message is 'scope: subject', known scope, under 72 chars."""
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
    """Build every target the module declares, reporting each one."""
    if m.empty:
        return skip(f"build {m.name}", "nothing to build yet")
    ok = True
    if m.idf_project:
        ok &= report(
            f"build {m.name}",
            run_in_module_shell(m, f"cd {m.idf_project} && idf.py build > /dev/null")
            == 0,
            "idf.py",
        )
    for d in m.ctest_dirs:
        ok &= report(
            f"build {m.name}/{d.relative_to(m.path)}", cmake(m, d) == 0, "cmake"
        )
    if m.native_lib:
        ok &= report(f"build {m.name}", cmake(m, m.native_lib) == 0, "cmake")
    if m.python_pkg:
        ok &= report(
            f"build {m.name}",
            run_in_module_shell(m, "python -c 'import sys'") == 0,
            "python",
        )
    return ok


def cmake(m: Module, source: Path) -> int:
    """Configure and build the source directory under .ci-build, returning the exit code."""
    out = CICD_BUILD / m.name / source.name
    return run_in_module_shell(
        m,
        f"cmake -S {source} -B {out} -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
        f" > /dev/null && cmake --build {out} > /dev/null",
    )


def check_test(m: Module) -> bool:
    """Run the module's ctest and pytest suites, reporting each."""
    if not m.ctest_dirs and not m.python_tests:
        return skip(f"test {m.name}", "no tests found")
    ok = True
    for d in m.ctest_dirs:
        out = CICD_BUILD / m.name / d.name
        rc = run_in_module_shell(m, f"ctest --test-dir {out} --output-on-failure")
        ok &= report(f"test {m.name}/{d.relative_to(m.path)}", rc == 0, "ctest")
    if m.python_pkg:
        if m.native_lib and cmake(m, m.native_lib) != 0:
            return ok and report(f"test {m.name}", False, "its library did not build")
        rc = run_in_module_shell(m, f"pytest {m.path} -q", quiet_on=(PYTEST_NO_TESTS,))
        if rc == PYTEST_NO_TESTS:
            ok &= skip(f"test {m.name}", "no tests found")
        else:
            ok &= report(f"test {m.name}", rc == 0, "pytest")
    return ok


def check_generated(mods: list[Module]) -> bool:
    """Report whether each declared generator reproduces its checked-in files unchanged."""
    ok = True
    for m in mods:
        if m.generated is None:
            continue
        rc = run_in_module_shell(m, f"cd {m.path} && {m.generated}")
        ok &= report(f"generated {m.name}", rc == 0, "regenerated, unchanged")
    return ok
