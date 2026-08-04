from dataclasses import dataclass
from pathlib import Path

from paths import ROOT


@dataclass
class Module:
    name: str
    path: Path
    idf_project: Path | None
    ctest_dirs: list[Path]
    python_pkg: bool
    cffi_build: Path | None

    @property
    def empty(self) -> bool:
        return not (self.idf_project or self.ctest_dirs or self.python_pkg)


def discover() -> list[Module]:
    mods = []
    for flake in sorted(ROOT.glob("*/flake.nix")):
        path = flake.parent
        idf = None
        for candidate in (path / "src", path):
            cml = candidate / "CMakeLists.txt"
            if cml.exists() and "project.cmake" in cml.read_text():
                idf = candidate
                break
        ctest = [
            d.parent
            for d in sorted(path.glob("*/CMakeLists.txt"))
            if d.parent.name in ("test", "tests")
        ]
        ctest += [d.parent for d in sorted(path.glob("test/*/CMakeLists.txt"))]
        mods.append(
            Module(
                name=path.name,
                path=path,
                idf_project=idf,
                ctest_dirs=sorted(set(ctest)),
                python_pkg=(path / "pyproject.toml").exists(),
                cffi_build=next(iter(sorted(path.glob("src/*/_build.py"))), None),
            )
        )
    return mods
