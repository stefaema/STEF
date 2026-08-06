import os
import subprocess
import sys
from pathlib import Path

from ci_cd.discovery import Module
from ci_cd.paths import CICD_RUNNER, HOOKS_PATH, ROOT
from ci_cd.ui import DIM, OFF, RED


def ensure_ci_shell() -> None:
    """Make sure CI tools are on PATH. If not, enter nix devshell that holds them."""
    if os.environ.get("STEF_CI_SHELL"):
        return
    os.environ["STEF_CI_SHELL"] = "1"
    os.execvp(
        "nix",
        [
            "nix",
            "develop",
            str(ROOT / "ci_cd"),
            "--command",
            sys.executable,
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


def get_git_output(*args: str) -> str:
    """Return the git command's stdout, empty if it failed."""
    p = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return p.stdout.strip()


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


def run_in_module_shell(
    module: Module, script: str, quiet_on: tuple[int, ...] = ()
) -> int:
    """Run the script in the module's own nix shell and return its exit code."""
    shell = f"./{module.path.relative_to(ROOT)}"
    return run_command(
        ["nix", "develop", shell, "--command", "bash", "-c", script],
        quiet_on=quiet_on,
    )


def get_module_shell_output(module: Module, script: str) -> str | None:
    """Return what the script printed in the module's nix shell, None unless it succeeded."""
    shell = f"./{module.path.relative_to(ROOT)}"
    p = subprocess.run(
        ["nix", "develop", shell, "--command", "bash", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return p.stdout.strip() or None if p.returncode == 0 else None


def get_current_branch() -> str:
    """Return the checked-out branch name."""
    return get_git_output("rev-parse", "--abbrev-ref", "HEAD")


def get_staged_files() -> list[Path]:
    """Return the repo-relative paths staged for commit that still exist on disk."""
    out = get_git_output("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [Path(p) for p in out.split() if (ROOT / p).exists()]


def get_tracked_files() -> list[Path]:
    """Return the repo-relative paths git tracks that still exist on disk."""
    out = get_git_output("ls-files")
    return [Path(p) for p in out.split() if (ROOT / p).exists()]
