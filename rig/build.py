import sys
from typing import TYPE_CHECKING

from rig.discovery import BUILDS, collect

if TYPE_CHECKING:
    from build123d import Part


def _export_stl(part: "Part", path):
    from build123d import export_stl

    export_stl(part, str(path))


def _export_3mf(part: "Part", path):
    from build123d import Mesher

    mesher = Mesher()
    mesher.add_shape(part)
    mesher.write(str(path))


EXPORTERS = {"stl": _export_stl, "3mf": _export_3mf}
DEFAULT_FORMATS = ("3mf",)


def main() -> None:
    """Export every part under src/, or one category, to out/ in the given --format (default 3mf)."""
    args = sys.argv[1:]

    formats = DEFAULT_FORMATS
    if "--format" in args:
        index = args.index("--format")
        formats = tuple(args.pop(index + 1).split(","))
        args.pop(index)

    unknown = [fmt for fmt in formats if fmt not in EXPORTERS]
    if unknown:
        print(
            f"unknown format(s): {', '.join(unknown)}, choose from {', '.join(EXPORTERS)}"
        )
        return

    category = args[0] if args and args[0] != "all" else None

    parts = collect(category)
    if not parts:
        where = f"src/{category}" if category else "src/"
        print(f"no module under {where} defines build() or sample()")
        return

    for name, part in parts.items():
        for fmt in formats:
            path = BUILDS / f"{name}.{fmt}"
            path.parent.mkdir(parents=True, exist_ok=True)
            EXPORTERS[fmt](part, path)
            print(path.relative_to(BUILDS.parent))


if __name__ == "__main__":
    main()
