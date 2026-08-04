import os
import shutil
import subprocess
import sys
from pathlib import Path

from discovery import Module
from paths import ROOT, RUNNER
from ui import DIM, OFF, RED

TOOLS = ("ruff", "clang-tidy")
HOOKS_PATH = "ci_cd/hooks"


def ensure_tools() -> None:
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
            str(RUNNER),
            *sys.argv[1:],
        ],
    )


def ensure_hooks() -> None:
    if not (ROOT / ".git").exists():
        return
    wanted = {"core.hooksPath": HOOKS_PATH, "merge.ff": "false"}
    changed = [k for k, v in wanted.items() if git("config", k) != v]
    for key in changed:
        git("config", key, wanted[key])
    if changed:
        print(f"{DIM}git config: {', '.join(changed)}{OFF}", file=sys.stderr)


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.stdout.strip()


def sh(cmd: list[str], cwd: Path = ROOT, quiet_on: tuple[int, ...] = ()) -> int:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"{RED}{cmd[0]} not found{OFF}", file=sys.stderr)
        return 127
    if p.returncode not in (0, *quiet_on):
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
    return p.returncode


def in_shell(module: Module, script: str, quiet_on: tuple[int, ...] = ()) -> int:
    return sh(
        ["nix", "develop", f"./{module.name}", "--command", "bash", "-c", script],
        quiet_on=quiet_on,
    )


def current_branch() -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD")


def staged_files() -> list[Path]:
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [Path(p) for p in out.split() if (ROOT / p).exists()]


def tracked_files() -> list[Path]:
    out = git("ls-files")
    return [Path(p) for p in out.split() if (ROOT / p).exists()]
