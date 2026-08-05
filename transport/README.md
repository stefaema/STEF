# Transport

This part of the project implements the PC-side client of the film transport. It speaks the
RPC protocol to the firmware over USB, and exposes the transport to the orchestrator as one
of its three subsystems.

## fw_api.py

The PC does not reimplement what the firmware implements. `CMakeLists.txt` compiles the
same sources into `librpc.so`, and `tools/fw_api_gen.py` reads the same headers with
libclang and writes `fw_api.py`: a `ctypes.Structure` per payload, an `IntEnum` per enum,
an int per constant, an exception per status, and `argtypes` with `restype` per function.
Sizes, offsets and enum values are the compiler's answer, so no name is written twice and
a method number cannot disagree across the link.

```
nix develop
python tools/fw_api_gen.py           # rewrite fw_api.py
python tools/fw_api_gen.py --check   # fail if it moved
```

`fw_api.py` is committed, so a header change arrives as a visible Python diff in the same
commit. `--check` is what keeps that honest, and `[tool.stef] generated` in
`pyproject.toml` is how `integration` finds it.

The generator refuses to run outside `nix develop`. It reads `LIBCLANG_PATH` and
`LIBC_INCLUDE` from the shell and passes `-nostdinc`, so the pinned clang parses against
pinned headers. Left to find its own toolchain it will produce different output on a
different machine, and a committed generated file cannot survive that.
