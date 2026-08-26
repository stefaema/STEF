import contextlib
import importlib
import os
import pkgutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from build123d import Part

# Path plumbing
SRC = Path(__file__).resolve().parent / "src"
BUILDS = Path(__file__).resolve().parent / "out"

CONVENTIONS = ("build", "sample")
PREFIXES = {"build": "", "sample": "samples/"}


@contextlib.contextmanager
def _stderr_silenced():
    """Patchy way to silence stderr during import of build123d, which can get noisy."""
    sys.stderr.flush()
    saved, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def collect(category: str | None = None) -> dict[str, "Part"]:
    """Collect build() and sample() across src/, or just src/<category> if given.

    Args:
        category: directory under src/ to scope to, or all of src/ if None.

    Returns:
        Output path stem (relative) to Part, ready for export.
    """
    sys.path.insert(0, str(SRC))
    with _stderr_silenced():
        importlib.import_module("build123d")

    root = SRC / category if category else SRC
    prefix = f"{category}." if category else ""

    found: dict[str, "Part"] = {}
    for module_info in pkgutil.walk_packages([str(root)], prefix=prefix):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        for convention in CONVENTIONS:
            # Check for a build() or sample() function in the module
            maker = getattr(module, convention, None)
            if maker is None:
                continue
            for stem, part in _named(maker(), module_info.name).items():
                found[f"{PREFIXES[convention]}{stem}"] = part
    return found


def _named(produced: "Part | dict[str, Part]", module_name: str) -> dict[str, "Part"]:
    """Normalize a single-part and a multi-part module to the same {name: Part} shape."""
    package, _, stem = module_name.rpartition(".")
    here = f"{package.replace('.', '/')}/{stem}" if package else stem
    if not isinstance(produced, dict):
        return {here: produced}
    return {f"{here}_{variant}": part for variant, part in produced.items()}
