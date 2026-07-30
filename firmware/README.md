# firmware

ESP32-S3 firmware for the film transport subsystem: three TMC2209 drivers on one
shared single-wire UART, plus per-driver STEP/DIR/EN/DIAG.

Scope: what this is, how to build, flash and test.

## What this is
The firmware part of the project consists of two libraries:

- `rpc`: Implements a Remote Procedure Call protocol consisting of a COBS delimited frame, CRC-16 validated.
- `tmc2209`: Implements a library capable of speaking to a TMC2209 driver using UART, control lines and a step generator.

Both libraries were designed to be system agnostic, so using them takes two more
components: `rpc_bind` and `tmc2209_bind`. These hold everything specific to the
project the libraries are used on, and here that is the configuration that makes
the film transport subsystem possible.

The main application completes the firmware. It sets up the drivers and
registers every `rpc` namespace, which turns the firmware into a
procedure-driven system: on its own it only does housekeeping, and otherwise
serves the requests the PC host makes.

## The toolchain
Two of the three things you can do here need an Xtensa cross compiler and a
matching ESP-IDF; the versions have to agree, and neither belongs in a system
package manager. `flake.nix` pins both, so every command below is prefixed with
`nix develop`, run from this directory:

```bash
cd firmware
nix develop
```

That shell exports `IDF_PATH` (ESP-IDF v5.5.2) and puts `idf.py`, `esptool.py`
and a Python with `pyserial` on `PATH`. The rest of this section assumes you are
inside it. To run a single command without staying in the shell, use
`nix develop --command <cmd>`.

## Tests
The `rpc` and `tmc2209` libraries are system agnostic, which means they compile
and run on the host as ordinary C. No ESP32, no toolchain and no cable is needed: the tests
build those same sources against a mock UART and fake bind layers.

```bash
cmake -S test/unit -B test/unit/build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build test/unit/build -j
ctest --test-dir test/unit/build --output-on-failure
```

Unity comes from `$IDF_PATH`, so the devShell covers it. Outside the shell, pass
`-DUNITY_DIR=/path/to/unity/src` instead.

`ctest` reports the suite as one pass or fail. For the per-case list, run the
binary directly:

```bash
./test/unit/build/unit_tests
```

The build directory is named `build` because `test/unit/.clangd` reads
`compile_commands.json` from there, which is also why the configure step exports
it.

## Building for the board
The firmware image is an ESP-IDF project rooted at `src/`. The target is
recorded in `sdkconfig`, which is gitignored, so a fresh clone sets it once:

```bash
cd src
idf.py set-target esp32s3
idf.py build
```

After that, `idf.py build` alone is enough; `set-target` regenerates `sdkconfig`
from `sdkconfig.defaults` and discards any menuconfig choices, so do not repeat
it casually. The build prints the app size against the partition it has to fit
in. Board wiring (UART pins, per-driver STEP/DIR/EN/DIAG, LED GPIO) lives in
Kconfig:

```bash
idf.py menuconfig
```

## Flashing
Which serial port the board lands on varies by OS and by what else is plugged
in, and the name alone does not tell you whether the device is an ESP32. This
matches connected devices against known bridge chips and Espressif's vendor ID,
then asks the chip to identify itself:

```bash
python ../utils/find_esp32_port.py
```

Add  `--port-only` to print
just the path for scripting. With the port known:

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

`flash` writes bootloader, partition table and app; `monitor` attaches the
console (exit with `Ctrl-]`). Dropping `-p` lets ESP-IDF autodetect, which is
fine when the board is the only serial device attached.

The console is the native USB port (USB-Serial/JTAG), not the UART bridge, per
`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG` in `sdkconfig.defaults`. Use the USB port
wired to the ESP32-S3 itself.

If the board will not take an image, or a stale partition layout is suspected:

```bash
idf.py -p /dev/ttyACM0 erase-flash
```
