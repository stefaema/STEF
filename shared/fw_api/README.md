# fw_api

The contract the firmware and the PC both compile: which procedures exist, what each one
takes and returns, and what a reply's status byte means. `include/fw_api.h` is that
declaration, and the firmware registers it as an ESP-IDF component. `rpc_strerror.c` carries
the one thing the header cannot state, the sentence each status answers to.

## abi.py

The PC does not reimplement what the firmware implements. `host/CMakeLists.txt` compiles the
same sources into `libfw_api.so`, and `tools/abi_gen.py` reads the same headers with
libclang and writes `abi.py`: a `ctypes.Structure` per payload, an `IntEnum` per enum, an
int per constant, an exception per status, `argtypes` with `restype` per function, and the
tables saying what C could only imply, which member is flexible and which typedef means a
bool or an enum. Sizes, offsets and enum values are the compiler's answer, so no name is
written twice and a method number cannot disagree across the link.

`abi.py` opens `build/libfw_api.so` at import, so the library is built before any Python
here runs, tests included.

```
nix develop
cmake -S host -B build/host && cmake --build build/host   # libfw_api.so
python tools/abi_gen.py           # rewrite abi.py
python tools/abi_gen.py --check   # fail if it moved
pytest                            # sizes, statuses, packing
cmake -S test -B build/test && cmake --build build/test && ctest --test-dir build/test
```

`abi.py` is committed, so a header change arrives as a visible Python diff in the same
commit. `--check` is what keeps that honest, and `[tool.stef] generated` in
`pyproject.toml` is how `integration` finds it.

The generator refuses to run outside `nix develop`. It reads `LIBCLANG_PATH` and
`LIBC_INCLUDE` from the shell and passes `-nostdinc`, so the pinned clang parses against
pinned headers. Left to find its own toolchain it will produce different output on a
different machine, and a committed generated file cannot survive that.

## api.py

ctypes lays out bytes and stops there: padding is visible, a flexible member's count has to
be maintained by hand, and a field the C declared `uint8_t` stays an int even when only a
typedef says it is a direction. `api.py` mirrors every payload as a dataclass without those
seams, types each field from the ABI's tables, and `encode`/`decode` move between the two.

The callable surface comes from the same enums. `namespaces()` pairs each namespace and
method with the payload structs their names predict, and `attach(carry)` binds all of them
to whatever will actually send a frame, so a transport gets `raw.halt(...)` without naming
a single method. `from shared import fw_api` reaches this file first and the generated
names behind it.
