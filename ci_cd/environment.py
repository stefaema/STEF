import json
import os
import subprocess
import sys
from pathlib import Path

from ci_cd.discovery import Module
from ci_cd.git import get_git_output
from ci_cd.paths import CICD_RUNNER, HOOKS_PATH, ROOT
from ci_cd.ui import DIM, OFF, RED


def ensure_ci_shell() -> None:
    """Make sure this runs inside the repository shell, re-executing into it if not."""
    if os.environ.get("STEF_CI_SHELL"):
        return
    os.environ["STEF_CI_SHELL"] = "1"
    os.execvp(
        "nix",
        [
            "nix",
            "develop",
            repo_shell(),
            "--command",
            "python",
            "-m",
            CICD_RUNNER,
            *sys.argv[1:],
        ],
    )


def ensure_git_hooks() -> None:
    """Point the repo's git config at our hooks, reporting only what it had to change."""
    if not (ROOT / ".git").exists():
        return
    wanted = {"core.hooksPath": HOOKS_PATH, "merge.ff": "false"}
    changed = [k for k, v in wanted.items() if get_git_output("config", k) != v]
    for key in changed:
        get_git_output("config", key, wanted[key])
    if changed:
        settings = ", ".join(f"{k}={wanted[k]}" for k in changed)
        print(f"{DIM}changed git config, CI needs {settings}{OFF}", file=sys.stderr)


def run_command(
    cmd: list[str], cwd: Path = ROOT, quiet_on: tuple[int, ...] = ()
) -> int:
    """Run the command and return its exit code, showing output only on unexpected failure."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print(f"{RED}{cmd[0]} not found{OFF}", file=sys.stderr)
        return 127
    if p.returncode not in (0, *quiet_on):
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
    return p.returncode


def module_shell(module: Module) -> str:
    """Return the flake reference for the module's shell, which the root flake names."""
    return f"{ROOT}#{module.name}"


def run_in_module_shell(
    module: Module, script: str, quiet_on: tuple[int, ...] = ()
) -> int:
    """Run the script in the module's own nix shell and return its exit code."""
    return run_command(
        ["nix", "develop", module_shell(module), "--command", "bash", "-c", script],
        quiet_on=quiet_on,
    )


def repo_shell() -> str:
    """Return the flake reference for the repository shell."""
    return f"{ROOT}#default"


def shells_on_this_system() -> set[str] | None:
    """Return the names of the shells the flake defines for this system, None if nix fails."""
    p = subprocess.run(
        [
            "nix",
            "eval",
            "--impure",
            "--json",
            f"{ROOT}#devShells",
            "--apply",
            "shells: builtins.attrNames shells.${builtins.currentSystem}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return set(json.loads(p.stdout)) if p.returncode == 0 else None
