import subprocess
from pathlib import Path

from ci_cd.paths import ROOT


def get_git_output(*args: str) -> str:
    """Return the git command's stdout, empty if it failed."""
    p = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return p.stdout.strip()


def get_current_branch() -> str:
    """Return the checked-out branch name."""
    return get_git_output("rev-parse", "--abbrev-ref", "HEAD")


def get_staged_files() -> list[Path]:
    """Return the repo-relative paths staged for commit that still exist on disk."""
    out = get_git_output("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    return [Path(p) for p in out.split("\0") if p and (ROOT / p).exists()]


def get_tracked_files(*patterns: str) -> list[Path]:
    """Return the repo-relative paths git tracks that still exist on disk."""
    out = get_git_output("ls-files", "-z", "--", *patterns)
    return [Path(p) for p in out.split("\0") if p and (ROOT / p).exists()]
