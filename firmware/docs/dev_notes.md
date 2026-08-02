# Firmware dev notes

## "Permission denied" on /dev/ttyACM0

`lsusb` works, `esptool`/`idf.py` fails:
```
Could not open /dev/ttyACM0: [Errno 13] Permission denied
```
User isn't in the group owning the device.
- Arch/CachyOS/Manjaro: `sudo usermod -aG uucp $USER`
- Debian/Ubuntu/Fedora/openSUSE: `sudo usermod -aG dialout $USER`

Needs re-login (or `newgrp <group>`) to apply. A new terminal alone isn't enough.


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
