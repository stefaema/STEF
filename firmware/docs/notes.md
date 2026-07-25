# Firmware dev notes

## Hardware interface (carrier ↔ driver boards)

Rationale for all of this is in `design.md`. Here: the facts you need at the
bench.

**Bus.** One shared single-wire UART for all three drivers. Addresses 0/1/2
strapped on MS1/MS2 per driver board. STEP/DIR/EN/DIAG are per-driver.
~14 GPIOs total (3×STEP, 3×DIR, 3×EN, 3×DIAG, TX, RX).

**RJ45, one per driver board, under 1 m:**

| Pair | Signals |
|---|---|
| Orange | STEP + GND |
| Green | DIR + EN |
| Blue | UART + GND |
| Brown | VCC logic (3.3V) + DIAG (not shared) |

Motor power (24 V) is **not** in the cable. Each driver board takes its own
feed.

**Gotchas, in rough order of how much they will cost you:**

- **`ENN` is active low, so pull it up to VIO on the driver board.** Floating
  means enabled. Without the pull-up, an ESP32 reset can leave three motors
  energized and pulling film with no firmware in control. `ENN` is the only
  kill path that works when firmware is hung or unflashed.
- **Join TX and RX at the carrier**, not at the driver: RX direct to the bus
  node, TX to the same node through 1 kΩ. One resistor total, not one per
  driver. Everything sent is then echoed back on RX and must be discarded.
- **The green pair is the weak one.** Orange and blue each pair a signal with
  GND; green pairs DIR with EN, so neither is a return. Mostly harmless since
  both are slow, except that **the driver latches DIR on the active STEP
  edge**, so a glitch coupled in at that instant is a step the wrong way. Set
  DIR a few µs before a burst, never mid-burst, and put a small RC on DIR at
  the driver board.
- **100 nF at the driver-board end of the VCC rail.** Pairing DIAG with a
  power rail is fine AC-wise only if that rail is decoupled at both ends.
- **MS1/MS2 also select microstep resolution at power-on**, before UART
  configuration lands (00→1/8, 01→1/2, 10→1/4). Since we strap them for
  addressing, the three motors boot at *different* resolutions. Harmless once
  `GCONF.mstep_reg_select = 1` is written, but do not send STEP pulses before
  configuring.
- **These are mechanically Ethernet jacks.** Someone will eventually plug one
  into a switch, or plug a network cable into the carrier, and we are putting
  a power rail on those pins. Key the connectors, label the keystones loudly,
  or accept it knowingly.

**Registers:** 23 of 24 readable; only 10 are configured and reflushed. Never
written: `FACTORY_CONF` (holds the factory oscillator trim) and `PWMCONF`
(auto-tuned better than we would). `OTP_PROG` is absent entirely, reachable
only by hand-assembled passthrough, on purpose. Table in `design.md` §1.

## "Permission denied" on /dev/ttyACM0

`lsusb` works, `esptool`/`idf.py` fails:
```
Could not open /dev/ttyACM0: [Errno 13] Permission denied
```
User isn't in the group owning the device.
- Arch/CachyOS/Manjaro: `sudo usermod -aG uucp $USER`
- Debian/Ubuntu/Fedora/openSUSE: `sudo usermod -aG dialout $USER`

Needs re-login (or `newgrp <group>`) to apply. A new terminal alone isn't enough.

## Console spins at 100% CPU, ignores keyboard input

`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` alone doesn't enable blocking stdin
or install the driver. Fix, in `app_main()` before reading stdin:
```c
usb_serial_jtag_driver_install(&cfg);
usb_serial_jtag_vfs_use_driver();
fcntl(fileno(stdin), F_SETFL, 0);
```

## About Device

Hardware tested:
- ESP32-S3 (QFN56, rev v0.2), WiFi+BLE, 8MB PSRAM, 16MB flash (Boya).

Verify: `python3 utils/find_esp32_port.py`
- Runs `esptool read_mac` (chip family/revision/features/PSRAM, read from
  eFuses over the ROM bootloader, can't be spoofed by a relabeled part)
  and `flash_id` (real flash size/manufacturer).
- Optional secondary check: module part number printed on the metal can
  (e.g. "ESP32-S3-WROOM-1-N16R8"). Visual only, the script's checks are
  already silicon-level and more trustworthy.

If the model changes, what needs updating:
- `flake.nix`: toolchain shell, different chip family = different compiler
  target (e.g. `esp32s3-idf` vs `esp32-idf`).
- `idf.py set-target <chip>`: re-run when switching chip family. Already
  happening every rebuild so far (`idf.py set-target esp32s3 && idf.py
  build`), not a separate manual step you'd normally run alone.
- `sdkconfig.defaults`: flash size, board-specific config.
- Source code: only if the new chip/board lacks a peripheral the firmware
  assumes (native USB-Serial/JTAG, WS2812 GPIO, etc.), not always.
