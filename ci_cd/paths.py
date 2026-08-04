from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".ci-build"
RUNNER = ROOT / "ci_cd" / "run.py"
