# fw_api

The contract the firmware and the PC both compile: which procedures exist, what each one
takes and returns, and what a reply's status byte means. `include/fw_api.h` is that
declaration, and the firmware registers it as an ESP-IDF component.

## abi.py

The PC does not reimplement what the firmware implements. `host/CMakeLists.txt` compiles the
same sources into `libfw_api.so`, and `tools/abi_gen.py` reads the same headers with
libclang and writes `abi.py`: a `ctypes.Structure` per payload, an `IntEnum` per enum,
an int per constant, an exception per status, and `argtypes` with `restype` per function.
Sizes, offsets and enum values are the compiler's answer, so no name is written twice and
a method number cannot disagree across the link.

```
nix develop
python tools/abi_gen.py           # rewrite abi.py
python tools/abi_gen.py --check   # fail if it moved
```

`abi.py` is committed, so a header change arrives as a visible Python diff in the same
commit. `--check` is what keeps that honest, and `[tool.stef] generated` in
`pyproject.toml` is how `integration` finds it.

The generator refuses to run outside `nix develop`. It reads `LIBCLANG_PATH` and
`LIBC_INCLUDE` from the shell and passes `-nostdinc`, so the pinned clang parses against
pinned headers. Left to find its own toolchain it will produce different output on a
different machine, and a committed generated file cannot survive that.

## api.py

`api.py` is the calling convention the ABI implies: it pairs each namespace and method enum
with the payload structs their names predict, and packs arguments straight into the struct
that goes on the wire. `from shared import fw_api` reaches both files, the surface first and
the generated names behind it.
