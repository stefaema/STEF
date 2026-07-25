# Firmware dev notes

## "Permission denied" running utils/find_esp32_port.py or idf.py flash

The board shows up (`lsusb`, and in the script's port list) but `esptool`
fails with:

```
A fatal error occurred: Could not open /dev/ttyACM0, the port is busy or doesn't exist.
([Errno 13] could not open port /dev/ttyACM0: [Errno 13] Permission denied: '/dev/ttyACM0')
```

This is a standard Linux serial-port permission gap, not a project or
toolchain bug. Your user needs to be in the group that owns the serial
device. Check which group that is first, since it differs by distro:

```
ls -l /dev/ttyACM0   # or /dev/ttyUSB0
```

Then add yourself to that group and **log out and back in** (group
membership only takes effect in new sessions):

- **Arch / CachyOS / Manjaro:** `sudo usermod -aG uucp $USER`
- **Debian / Ubuntu / Raspberry Pi OS / Linux Mint:** `sudo usermod -aG dialout $USER`
- **Fedora / RHEL / openSUSE:** `sudo usermod -aG dialout $USER`

After logging back in, re-run `python3 utils/find_esp32_port.py` and the
`read_mac`/`flash_id` steps should succeed instead of erroring.

## Multiple firmware images (planned, not built yet)

There will be more than one firmware for this board, not one binary that
does everything:

- **Self-test** (exists today, `main/selftest_main.c`): board/chip identity,
  LED, later WiFi/GPIO-loopback. Never touches the driver bus or motors.
- **Driver test** (not built yet): the "echo" idea from earlier design
  discussion, ESP32 as a transparent UART passthrough to the TMC2209 so the
  existing PC-side driver test suite can exercise the real driver without
  duplicating register logic in firmware.
- **Production** (not built yet): the real RPC-driven control firmware.

These are separate compiled firmware images (ESP-IDF's `multi_config`
pattern: one `Kconfig.projbuild` choice selects which `main/*.c` entry
point compiles in, each variant gets its own build dir / sdkconfig), not
runtime-switchable modes in one binary. Reasoning: anything that can drive
the STEP/DIR/EN pins shouldn't be reachable except by a deliberate reflash,
since those pins actuate real motors near a loaded film path. See the
design discussion in conversation for the full reasoning, short version:
passive/read-only diagnostics (chip identity, reset reason) are cheap and
safe to keep always-available at runtime; anything that can actuate output
pins should require a reflash to even be reachable, not a runtime command.
