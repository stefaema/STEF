import math
import os
import sys
import threading
from typing import TYPE_CHECKING

from rig.discovery import collect

if TYPE_CHECKING:
    from build123d import Part

GUTTER = 10.0  # mm between parts bounding boxes in the grid
SHUTDOWN_GRACE = 5.0  # seconds given to yacv_server to shut down before it is killed


def laid_out(parts: dict[str, "Part"]) -> dict[str, "Part"]:
    """Place parts on a grid, spaced GUTTER apart, so yacv shows them without overlap."""
    from build123d import Pos

    boxes = {name: part.bounding_box() for name, part in parts.items()}
    cell_x = max(box.size.X for box in boxes.values()) + GUTTER
    cell_y = max(box.size.Y for box in boxes.values()) + GUTTER
    columns = math.ceil(math.sqrt(len(parts)))

    placed: dict[str, "Part"] = {}
    for index, (name, part) in enumerate(parts.items()):
        box = boxes[name]
        row, column = divmod(index, columns)
        placed[name] = (
            Pos(
                column * cell_x - box.center().X,
                -row * cell_y - box.center().Y,
                -box.min.Z,
            )
            * part
        )
    return placed


def main() -> None:
    """Collect build() and sample() across the category, and serve them for yacv to view."""
    if len(sys.argv) < 2:
        print("usage: python -m rig.view <category|all> [name filter]")
        print("category is a directory under src/, e.g. mounts or rollers")
        return
    category = sys.argv[1] if sys.argv[1] != "all" else None
    wanted = sys.argv[2] if len(sys.argv) > 2 else ""

    found = collect(category)
    if not found:
        where = f"src/{category}" if category else "src/"
        print(f"no module under {where} defines build() or sample()")
        return

    shown = {name: found[name] for name in sorted(found) if wanted in name}
    if not shown:
        print(f"no part name contains {wanted!r}")
        return

    from yacv_server import show

    shown = laid_out(shown)
    for name in shown:
        print(name)
    show(*shown.values(), names=list(shown.keys()))  # pyright: ignore[reportArgumentType]

    host = os.getenv("YACV_HOST", "localhost")
    port = os.getenv("YACV_PORT", "32323")
    print(f"serving http://{host}:{port} until Ctrl-C", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("stopping", flush=True)
        # yacv_server's threads are not daemons, so a plain exit would hang; force it if they don't.
        watchdog = threading.Timer(SHUTDOWN_GRACE, lambda: os._exit(0))
        watchdog.daemon = True
        watchdog.start()


if __name__ == "__main__":
    main()
