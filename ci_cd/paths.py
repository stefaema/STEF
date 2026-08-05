from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CICD_BUILD = ROOT / ".ci-build"
CICD_RUNNER = ROOT / "ci_cd" / "run.py"
HOOKS_PATH = "ci_cd/hooks"
