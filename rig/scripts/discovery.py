import contextlib
import importlib
import os
import pkgutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from build123d import Part

SRC = Path(__file__).resolve().parent.parent / "src"
BUILDS = Path(__file__).resolve().parent.parent / "builds"

CONVENTIONS = ("build", "sample")


@contextlib.contextmanager
def _stderr_silenced():
    sys.stderr.flush()
    saved, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def collect() -> dict[str, "Part"]:
    sys.path.insert(0, str(SRC))
    with _stderr_silenced():
        importlib.import_module("build123d")

    found: dict[str, "Part"] = {}
    for module_info in pkgutil.walk_packages([str(SRC)]):
        if module_info.ispkg:
            continue
        module = importlib.import_module(module_info.name)
        for convention in CONVENTIONS:
            maker = getattr(module, convention, None)
            if maker is None:
                continue
            here = module_info.name.replace(".", "/")
            found[f"{here}/{convention}"] = maker()
    return found
