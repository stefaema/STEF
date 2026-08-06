import tomllib
from dataclasses import dataclass
from pathlib import Path

from ci_cd.paths import ROOT

DERIVED_DIRS = {"build", ".ci-build", "__pycache__", ".git"}
TEST_DIR_NAMES = ("test", "tests")
IDF_MARKER = "project.cmake"


@dataclass
class Module:
    """A repo module and every CI capability discovered under it."""

    name: str
    path: Path
    idf_project: Path | None
    ctest_dirs: list[Path]
    native_lib: Path | None
    python_pkg: bool
    python_files: bool
    python_tests: bool
    generated: str | None

    @property
    def empty(self) -> bool:
        """Whether the module has no buildable target."""
        return not (
            self.idf_project or self.ctest_dirs or self.native_lib or self.python_pkg
        )


def authored(path: Path, pattern: str) -> list[Path]:
    """Return the pattern's matches under path, skipping build output."""
    return [
        p
        for p in sorted(path.rglob(pattern))
        if not DERIVED_DIRS & set(p.relative_to(path).parts)
    ]


def module_roots() -> list[Path]:
    """Return every module directory, which this nix-based repo marks with a flake.nix.

    A directory that carries no flake.nix of its own only groups modules, so the
    search descends one level into it.
    """
    top = [flake.parent for flake in ROOT.glob("*/flake.nix")]
    grouped = [
        flake.parent
        for flake in ROOT.glob("*/*/flake.nix")
        if flake.parent.parent not in top
    ]
    return sorted(top + grouped)


def is_esp_idf_based(cmake_dir: Path) -> bool:
    """Whether the directory's CMakeLists.txt pulls in ESP-IDF's project.cmake."""
    cml = cmake_dir / "CMakeLists.txt"
    return cml.exists() and IDF_MARKER in cml.read_text()


def is_cmake_project(cmake_dir: Path) -> bool:
    """Whether the directory's CMakeLists.txt declares a project."""
    cml = cmake_dir / "CMakeLists.txt"
    return cml.exists() and "project(" in cml.read_text()


def esp_idf_dir(module: Path) -> Path | None:
    """Return the module's firmware directory, either src or the module root."""
    return next((d for d in (module / "src", module) if is_esp_idf_based(d)), None)


def native_lib_dir(module: Path) -> Path | None:
    """Return the host-buildable CMake project, either host or the module root."""
    return next(
        (
            d
            for d in (module / "host", module)
            if not is_esp_idf_based(d) and is_cmake_project(d)
        ),
        None,
    )


def c_test_dirs(module: Path) -> list[Path]:
    """Return every CTest source directory, whether one test dir or several under test."""
    own = [
        cml.parent
        for cml in module.glob("*/CMakeLists.txt")
        if cml.parent.name in TEST_DIR_NAMES
    ]
    grouped = [cml.parent for cml in module.glob("test/*/CMakeLists.txt")]
    return sorted(set(own + grouped))


def is_python_package(module: Path) -> bool:
    """Whether the module declares a pyproject.toml."""
    return (module / "pyproject.toml").exists()


def has_py_files(module: Path) -> bool:
    """Whether the module holds any authored Python for the linters to check."""
    return bool(authored(module, "*.py"))


def has_py_tests(module: Path) -> bool:
    """Whether the module holds files pytest would collect."""
    return bool(authored(module, "test_*.py") or authored(module, "*_test.py"))


def regen_command(module: Path) -> str | None:
    """Return the command the module declares for regenerating its checked-in files."""
    pyproject = module / "pyproject.toml"
    if not pyproject.exists():
        return None
    with pyproject.open("rb") as f:
        tools = tomllib.load(f).get("tool", {})
    return tools.get("stef", {}).get("generated")


def discover() -> list[Module]:
    """Return every module in the repo with its CI capabilities filled in."""
    return [
        Module(
            name=module.name,
            path=module,
            idf_project=esp_idf_dir(module),
            ctest_dirs=c_test_dirs(module),
            native_lib=native_lib_dir(module),
            python_pkg=is_python_package(module),
            python_files=has_py_files(module),
            python_tests=has_py_tests(module),
            generated=regen_command(module),
        )
        for module in module_roots()
    ]
