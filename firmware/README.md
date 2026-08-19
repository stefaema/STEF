# firmware

ESP32-S3 firmware for the film transport subsystem: three TMC2209 drivers on one
shared single-wire UART, plus per-driver STEP/DIR/EN/DIAG.

## What this is

`portable/rpc` and `portable/tmc2209` are system agnostic, so using them takes
two more components, `rpc_bind` and `tmc2209_bind` under `src/components/`,
which hold everything specific to this project. The main application sets up
the drivers and registers every `rpc` namespace: on its own it only does
housekeeping, and otherwise serves the requests the PC host makes.

## The toolchain

Building needs an Xtensa cross compiler and a matching ESP-IDF, at versions that
agree. `flake.nix` pins both, so every command below runs inside:

```bash
cd firmware
nix develop
```

That shell exports `IDF_PATH` (ESP-IDF v5.5.2) and puts `idf.py`, `esptool.py`
and a Python with `pyserial` on `PATH`.

## Tests

The libraries compile and run on the host as ordinary C, against a mock UART and
fake bind layers. No board, no toolchain, no cable. `ci_cd` builds and runs them:

```bash
python -m ci_cd.run test firmware
```

For the per-case list rather than one pass or fail, build under `test/unit/build`
and run the binary, which is also where `test/unit/.clangd` expects the compile
database:

```bash
cmake -S test/unit -B test/unit/build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build test/unit/build -j
./test/unit/build/unit_tests
```

Unity comes from `$IDF_PATH`. Outside the shell, pass
`-DUNITY_DIR=/path/to/unity/src`.

## Building for the board

The image is an ESP-IDF project rooted at `src/`. The target is recorded in
`sdkconfig`, which is gitignored, so a fresh clone sets it once:

```bash
cd src
idf.py set-target esp32s3
idf.py build
```

`set-target` regenerates `sdkconfig` from `sdkconfig.defaults` and discards any
menuconfig choices, so do not repeat it casually. Board wiring (UART pins,
per-driver STEP/DIR/EN/DIAG) lives in Kconfig, reached with
`idf.py menuconfig`.

## Flashing

Which serial port the board lands on varies by OS and by what else is plugged
in:

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

`flash` writes bootloader, partition table and app; `monitor` attaches the
console (exit with `Ctrl-]`). Dropping `-p` lets ESP-IDF autodetect, which is
fine when the board is the only serial device attached.

The console is UART0 on GPIO43 and GPIO44, per `CONFIG_ESP_CONSOLE_UART_DEFAULT`
in `sdkconfig.defaults`, with no secondary console. The boot log says which pins
it took, so it is worth reading when nothing arrives.

Changing that is a menuconfig job rather than an edit to `sdkconfig.defaults`: a
key already present in `sdkconfig` wins over the default, so editing the default
alone changes nothing on a tree that has already been configured.

If the board will not take an image, or a stale partition layout is suspected,
`idf.py -p /dev/ttyACM0 erase-flash`.
