#!/usr/bin/env python3
"""Locate the serial port an ESP32 board is attached to.

Matches connected USB devices against known ESP32 USB-UART bridge chips and
Espressif's own native-USB vendor ID, rather than guessing from port names
(which vary across ttyUSB*/ttyACM*/cu.usbserial* depending on the OS and the
number of other USB-serial devices attached).

Run inside the firmware devShell (`nix develop`), it needs pyserial, which
ships as an esptool dependency there.

By default also asks the chip who it is (MAC + detected chip type, flash
manufacturer/size) via esptool, since a board matching known bridge chips
doesn't guarantee it's genuine or the chip variant you expect. Pass
--port-only to skip that and just print the port path, for use in scripts.

Pass --wait SECONDS to poll instead of checking once, useful if you only
have one free data-capable cable/port and need a moment to move it from
something else to the board.
"""
import argparse
import subprocess
import sys
import time

from serial.tools import list_ports

# (vendor_id, product_id) -> human description. product_id of None matches
# any product from that vendor.

KNOWN_BRIDGES = {
    (0x303A, None): "Espressif native USB (USB-Serial/JTAG or native USB CDC)",
    (0x10C4, None): "Silicon Labs CP210x USB-UART bridge",
    (0x1A86, None): "WCH USB-UART bridge (CH340/CH341/CH9102 family)",
    (0x0403, None): "FTDI USB-UART bridge",
}


def describe(vid, pid):
    if vid is None:
        return None
    if (vid, pid) in KNOWN_BRIDGES:
        return KNOWN_BRIDGES[(vid, pid)]
    return KNOWN_BRIDGES.get((vid, None))


def find_candidates():
    return [(port, describe(port.vid, port.pid)) for port in list_ports.comports()]


def wait_for_candidates(timeout):
    """Poll until a matching device shows up or the timeout elapses.

    Returns whatever find_candidates() last saw, matched or not, so the
    caller reports the same way whether we waited or not.
    """
    deadline = time.monotonic() + timeout
    while True:
        candidates = find_candidates()
        if any(match is not None for _, match in candidates):
            print(file=sys.stderr)
            return candidates

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(file=sys.stderr)
            return candidates

        print(f"\rWaiting for an ESP32 device... {remaining:4.1f}s left (plug it in now)",
              end="", file=sys.stderr, flush=True)
        time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port-only",
        action="store_true",
        help="print only the matched port path (no chip probe), for use in scripts",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="poll for up to SECONDS for a device to appear, instead of checking once",
    )
    args = parser.parse_args()

    candidates = wait_for_candidates(args.wait) if args.wait > 0 else find_candidates()
    matches = [(port, match) for port, match in candidates if match is not None]

    if not args.port_only:
        print("Serial ports found:", file=sys.stderr)
        for port, match in candidates:
            vidpid = f"{port.vid:04x}:{port.pid:04x}" if port.vid is not None else "?"
            tag = f"  <- {match}" if match else ""
            print(f"  {port.device}  [{vidpid}]  {port.description}{tag}", file=sys.stderr)
        print(file=sys.stderr)

    if not matches:
        print("No ESP32-like USB device found.", file=sys.stderr)
        sys.exit(1)

    if len(matches) > 1:
        print(
            "Multiple ESP32-like devices found, unplug all but one or pass "
            "the port explicitly to idf.py/esptool:",
            file=sys.stderr,
        )
        for port, match in matches:
            print(f"  {port.device}  ({match})", file=sys.stderr)
        sys.exit(2)

    port, match = matches[0]

    if args.port_only:
        print(port.device)
        return

    print(f"Found: {port.device} ({match})", file=sys.stderr)
    print(file=sys.stderr)

    print("--- esptool read_mac (confirms chip type + genuine Espressif MAC) ---", file=sys.stderr)
    subprocess.run(["esptool.py", "--port", port.device, "read_mac"], check=False)

    print(file=sys.stderr)
    print("--- esptool flash_id (flash manufacturer + real size) ---", file=sys.stderr)
    subprocess.run(["esptool.py", "--port", port.device, "flash_id"], check=False)


if __name__ == "__main__":
    main()
