import tomllib
from dataclasses import dataclass
from pathlib import Path

from ci_cd.paths import ROOT

DERIVED_DIRS = {"build", ".ci-build", "__pycache__", ".git"}


@dataclass
class Module:
    name: str
    path: Path
    idf_project: Path | None
    ctest_dirs: list[Path]
    native_lib: Path | None
    python_pkg: bool
    python_files: bool
    generated: str | None

    @property
    def empty(self) -> bool:
        return not (
            self.idf_project or self.ctest_dirs or self.native_lib or self.python_pkg
        )


def declared_check(pyproject: Path) -> str | None:
    if not pyproject.exists():
        return None
    with pyproject.open("rb") as f:
        tools = tomllib.load(f).get("tool", {})
    return tools.get("stef", {}).get("generated")


def authored(path: Path, pattern: str) -> list[Path]:
    return [
        p
        for p in sorted(path.rglob(pattern))
        if not DERIVED_DIRS & set(p.relative_to(path).parts)
    ]


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

        root_cml = path / "CMakeLists.txt"
        native = (
            path
            if idf != path and root_cml.exists() and "project(" in root_cml.read_text()
            else None
        )

        pyproject = path / "pyproject.toml"
        mods.append(
            Module(
                name=path.name,
                path=path,
                idf_project=idf,
                ctest_dirs=sorted(set(ctest)),
                native_lib=native,
                python_pkg=pyproject.exists(),
                python_files=bool(authored(path, "*.py")),
                generated=declared_check(pyproject),
            )
        )
    return mods
