# Transport

This part of the project implements the PC-side client of the film transport. It speaks the
RPC protocol to the firmware over USB, and exposes the transport to the orchestrator as one
of its three subsystems.

The contract it speaks is `shared/fw_api`, which carries both the C declaration the firmware
compiles and the ctypes view this module imports.

## Knowing what is on a port

A serial port's name says nothing about what is on it, and neither does its USB
descriptor. Four vendor IDs turn up on ESP32 boards, and three of them are
generic USB-UART bridges: a bridge chip tells you a UART is on the far side,
never what is on the far side of the UART. Espressif's own `0x303a` is the one
exception, and it only appears on native-USB parts. So the descriptor can
shortlist a port and can never settle one.

Settling it means talking, and there are two ends to talk to.

| tier | asks | costs | settles |
| --- | --- | --- | --- |
| descriptor | `fw.probe.candidates()` | nothing | which ports are worth trying |
| app | `sys.version` over the link | one round trip | that this is *our* firmware, and which build |
| ROM | `rom.detect()`, esptool | a reset into the bootloader | that this is an ESP32, and which chip |

The app tier says more than the ROM tier, not less, so `fw.probe.identify()`
asks it first and never resets a board that is working. Only silence is
ambiguous, and only silence is worth a reset to resolve, which is why the ROM
tier lives under `bench/` and nothing on the connect path reaches it.

`identify()` returns one of five findings, and each is a different sentence
because each has a different remedy: the pinned firmware answering, another
build answering, a protocol the PC cannot read, silence, and a port that is gone
or will not open. `can_connect` runs the same call and blocks with the same
sentence, so a disabled Connect button names what it found rather than asking
the operator to go and run something first.

## Which firmware is the right one

`fw.image` reads the inventory under `paths.firmware_bins()`, one directory per
version. A directory and not a file: an ESP-IDF board needs a bootloader, a
partition table and an app at three offsets that only the build knows, so the
unit is those binaries plus the `manifest.json` recording where each goes and
what it hashes to.

Which of them this installation runs is pinned in `config_dir()/firmware.toml`,
never inferred. Taking the newest installed would mean that dropping a file into
a directory silently upgrades the deployment. With no pin, one installed release
is the only answer available and several is a question only the operator can
settle, so `auto` refuses rather than guessing.

## Layout

| file | what it answers |
| --- | --- |
| `fw/framing.py` | framing, and what a frame carries |
| `fw/link.py` | a firmware on the other end of a port, and the calls it serves |
| `fw/probe.py` | who is on a port, without disturbing them |
| `fw/image.py` | what is installed here, and which of it this machine runs |
| `transport.py` | the subsystem the bench sees, and the link it is reached through |
| `device_profile.py` | which registers a driver is given, and what it is called |
| `bench/rom.py` | what the bootloader answers, and how an image gets written |

## What an operator runs

Everything the screen offers is a `bench_api` routine, and `bench/` holds one
module per stage of the link's life. A module's name is the group its routines
answer to, so where a routine lives is what it is called:

| module | category | what it holds |
| --- | --- | --- |
| `bench/link.py` | `LINK` | connect and disconnect, and what blocks each |
| `bench/prelink.py` | `PRELINK` | the ladder, and flashing, while nothing holds the port |
| `bench/setup.py` | `SETUP` | bringing a driver up to its baseline, once the link is open |
| `bench/calls.py` | `CALL` | one routine per firmware method, declared in a loop |

`prelink` runs only while the link is down, since both the probe ladder and a
flash need the port to themselves. `setup` and `calls` run only while it is up.
The category carries that rule, so neither module states it again.

`calls.py` writes none of its twenty-six routines out. `fw_api` already
generates one annotated dataclass per firmware method, which is what a form
derives from, so the declarations are made in a loop over the ABI and a header
change moves them without an edit here.

A declaration module must not look like a test module, or pytest collects it,
imports it a second time, and every routine in it registers twice.

## Tests

```bash
python -m ci_cd.run test transport
```
