from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CICD_BUILD = ROOT / ".ci-build"
CICD_RUNNER = "ci_cd.run"
HOOKS_PATH = "ci_cd/hooks"
