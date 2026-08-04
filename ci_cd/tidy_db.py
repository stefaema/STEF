import functools
import json
import os
import shlex
import subprocess
from pathlib import Path

from paths import BUILD, ROOT

GCC_ONLY = {
    "-mlongcalls",
    "-mtext-section-literals",
    "-mdisable-hardware-atomics",
    "-fno-tree-switch-conversion",
    "-fno-inline-small-functions",
    "-fno-inline-functions-called-once",
    "-fstrict-volatile-bitfields",
    "-fno-shrink-wrap",
}


@functools.lru_cache(maxsize=None)
def system_includes(driver: str) -> tuple[str, ...]:
    probe = subprocess.run(
        [driver, "-xc", "-E", "-v", "-"], input="", capture_output=True, text=True
    )
    dirs, collecting = [], False
    for line in probe.stderr.splitlines():
        if line.startswith("#include <...>"):
            collecting = True
        elif line.startswith("End of search list"):
            break
        elif collecting:
            dirs.append(os.path.normpath(line.strip()))
    if not dirs:
        return ()
    return ("-nostdlibinc", *[a for d in dirs for a in ("-isystem", d)])


def sources() -> list[Path]:
    dirs = [p.parent for p in sorted(BUILD.glob("*/*/compile_commands.json"))]
    firmware = ROOT / "firmware" / "src" / "build"
    if (firmware / "compile_commands.json").exists():
        dirs.append(firmware)
    return dirs


def rewritten_for_clang(dbs: list[Path]) -> tuple[Path, set[str]] | None:
    merged: dict[str, dict] = {}
    for src in dbs:
        db = src / "compile_commands.json"
        if not db.exists():
            continue
        for e in json.loads(db.read_text()):
            if not e["file"].startswith(str(ROOT)) or not e["file"].endswith(
                (".c", ".cpp")
            ):
                continue
            argv = shlex.split(e["command"]) if "command" in e else list(e["arguments"])
            argv = [
                a
                for a in argv
                if a not in GCC_ONLY and not a.startswith("-fmacro-prefix-map=")
            ]
            if "xtensa" in Path(argv[0]).name:
                argv.append("-D__XTENSA__")
            argv += [
                "-Wno-unknown-attributes",
                "-Wno-ignored-attributes",
                *system_includes(argv[0]),
            ]
            e.pop("arguments", None)
            e["command"] = shlex.join(argv)
            merged[e["file"]] = e

    if not merged:
        return None

    dst = BUILD / "tidy"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "compile_commands.json").write_text(
        json.dumps(list(merged.values()), indent=2)
    )
    return dst, set(merged)
