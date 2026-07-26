# Firmware roadmap

Planning and status. What a component *is* belongs in `docs/development/`. This file records only what exists, what
is next, and what is needed physically to check any of it.

Fixtures come first because everything below refers to them.

## Fixtures

A fixture is the physical setup a test needs. They are numbered and written
down because a rig nobody can rebuild is a rig that ran once and wasn't tested.

Each is the previous one plus one thing.

### F1. ESP32 + USB

Nothing else attached. One optional jumper between two GPIOs, named by number
in the test itself, for the pulse-counting check.

### F2. F1 + one driver

One TMC2209 on a breakout, strapped to address 0.

- **`ENN` pulled up to VIO, in place before power ever exists.** Floating means
  enabled. This is the only kill path that works when firmware is hung or
  unflashed.
- **TX joined to RX through 1 kΩ at the carrier side.** RX goes direct to the
  bus node, TX reaches the same node through the resistor. One resistor total,
  not one per driver.
- 100 nF at the driver end of the 3.3 V rail.
- Small RC on DIR at the driver board.

Motor power present, motor not connected.

The TMC2209 answers UART on logic power alone, so the whole register suite runs
before 24 V is connected. Worth a dry pass on first wiring, where the worst
outcome of a mistake is silence. That is a convenience, not a separate fixture.

### F3. F2 + motor

Unloaded first, then loaded by hand. Rotation becomes visible here, load can be
applied deliberately, and StallGuard stops being a number and starts meaning
something.

No STEP pulses until `GCONF.mstep_reg_select = 1` is written. MS1/MS2 select
microstep resolution at power-on and we strap them for addressing, so drivers
boot at differing resolutions.

### F4. Carrier board + driver boards + motors

Belongs to `boards/`, not to this stage. It is listed because **the Integrity
suite runs on it unchanged**: driver count and addresses are parameters, so F4
is a configuration and not a rewrite.

## Components

ESP32 side, bottom to top.

| Component | Owns | State | Verified by |
|---|---|---|---|
| `tmc2209` | UART framing, CRC, echo verification, IFCNT-verified writes, the ownership-classified register cache, condition polling, passthrough. Zero dependencies, not even ESP-IDF.| built, `src/components/tmc2209/` | Unit |
| `stepgen` | STEP/DIR/EN timing on ESP32 peripherals: a requested rate becomes peripheral configuration and pulses on a pin, with DIR set before a burst and never during one. | not started | Unit for the rate arithmetic, Integrity for pulses on the pins |
| `rpc` | The PC-facing protocol, three modes: smart, raw, passthrough. Uses the library internally and does not duplicate protocol logic. | not started | Unit for the envelope, Integrity for passthrough and raw |
| `actuator` | One `stepgen` plus one `tmc2209` each, three of them: `feed`, `capstan`, `takeup`. Calibration, and enforcing the `VACTUAL == 0` precondition before coordinated motion. Not "axis": these rotate continuously with no bounded travel to home to. | not started | HIL |

Two things deliberately do not appear as components.

**The ESP-IDF port adapter** lives in `main/tmc_bus.c`. The library's only
contact with hardware is the function pointers in `tmc2209_port_t`, so the
adapter is the forty lines that wrap `uart_write_bytes` and `uart_read_bytes`
into that shape, set `echoes = true`, and hand back a configured
`tmc2209_bus_t`. Which UART port, which GPIOs and which baud rate are
application decisions, which is what `main` is for. It stays outside
`components/tmc2209/` so the library keeps compiling with no ESP-IDF present,
which is what lets the unit suite run on a PC.

**The PC-side tool** that drives Integrity and HIL is not firmware. It is a
shipped diagnostic rather than a test script, so it belongs with the PC
software.

## Test levels

Three, named for what is real in each.

### Unit

`test/unit/`. Natively compiled, no ESP32, no silicon.

~100 Unity tests. Runs against a mock that models the device rather than replaying
scripted bytes, so tests read as "the register should now hold X". Fault
injection covers CRC corruption, echo corruption, silence, wrong-register
replies and uncounted writes. CRC vectors come from the Python library that ran
on real silicon, so passing means agreeing with hardware and not with ourselves.

Classification and configuration-coverage assertions are load-bearing: a suite
that only checks the device against the cache cannot catch a wrong cache, which
is `design.md` §7 item 7.

```
cmake -S firmware/test/unit -B build-unit && cmake --build build-unit
ctest --test-dir build-unit --output-on-failure
```

Unity comes from ESP-IDF when `IDF_PATH` is set, so enter the nix shell or pass
`-DUNITY_DIR=`.

### Integrity

The shipped diagnostic, not scaffolding. Its user is whoever is holding the
hardware: swap a driver and you need to know the replacement is a real TMC2209
and not an offbrand part with no UART; swap an ESP32 and you need to know the
new one has the same capabilities. That makes passthrough and telemetry
**product features** rather than test hooks.

Two stages, and **the order is a dependency and not a preference**: a dead GPIO
or a miswired UART on the ESP32 produces exactly the symptoms of a bad driver,
so a driver verdict from an unverified ESP32 is not evidence of anything.

**Stage 1, the ESP32. F1.**

- Chip family, revision, features and PSRAM, read from eFuses over the ROM
  bootloader. A relabeled part cannot spoof these. Real flash size and
  manufacturer alongside.
- RPC answers and reports its build.
- Every STEP pin actually pulses, counted on-chip by PCNT, so the assertion is
  closed-loop and needs no scope.
- DIR and ENN drive and read back.
- UART1 transmits and receives in loopback.

**Stage 2, the driver. F2, and only once stage 1 passes.**

- It answers at its address at all, with a CRC that validates.
- `IOIN.VERSION` reads `0x21`, the part's identity byte.
- `IFCNT` increments by exactly one per write. An echo alone does not prove the
  write landed.
- `GCONF` and `CHOPCONF` write and read back. They are the only two `OWNED`
  registers the silicon answers for.
- Write-only registers stay unreadable. A naive emulator answers them.
- `CONSTANT` registers hold their expected values.
- A deliberately corrupted datagram gets **no reply**. This proves the part
  validates CRC rather than pattern-matching a request shape, and it is the
  hardest test here for a fake to pass.

Driven through passthrough, so the verdict is about the driver and not about
our firmware's reading of it. Runs at F2 and at F4 with no change.

### HIL

F3. Full stack: PC, RPC, firmware, driver, motor.

Verified three ways, and all three earn their place because each catches what
the others cannot. Register readback is precise but only proves intent.
Telemetry (`TSTEP`, `DRV_STATUS`, StallGuard under load) shows what the silicon
is experiencing. Watching the thing turn catches everything that agreed with
itself and was still wrong.

This is where coordinated motion across three actuators gets proven, and where
the `VACTUAL == 0` precondition earns its keep.

## Queue

Ordered, each item naming what gates it.

1. `stepgen` rate arithmetic plus unit tests. Gate: none.
2. RPC envelope plus unit tests, all three modes in the schema. Gate: none. A
   mode tag retrofitted later is a breaking change, so the schema is designed
   whole even though the modes go live in stages.
3. ESP-IDF port adapter in `main/tmc_bus.c`. Gate: none to write, F1 to check.
4. Build F1. Gate: the bench.
5. `stepgen` on real peripherals, and Integrity stage 1. Gate: 3, 4.
6. Build F2. Gate: 5 green.
7. RPC passthrough and raw, and Integrity stage 2. Gate: 6.
8. Build F3, then `actuator` and smart mode. Gate: 7 green.

Items 1 to 3 need no hardware, so they run in parallel with building F1.

## Deferred, on purpose

Each with the reason and with the trigger that would undefer it, so "why is
this not built" has an answer that is not archaeology. All three are recorded
in `design.md` §8.

- **Link statistics.** Per-device retry and error counters. A bus that silently
  retries on every transaction currently looks identical to a healthy one.
  Trigger: the first unexplained flake.
- **Strap cross-check.** The driver answering at address N should have MS1/MS2
  straps consistent with N. Blocked on confirming the address-to-strap bit
  mapping against the datasheet.
- **SIL.** A PC-side TMC2209 simulator behind the same `tmc2209_port_t`, with
  `echoes = false` because the link is full duplex. Not a test level: it is HIL
  with the silicon substituted, which is why `design.md` §4 gives it a port
  backend and not a layer of its own. A real driver at F2 is a better reference
  model than a simulator we would write and then have to trust, and its one
  remaining job is running the suite with nothing plugged in. The cost of
  deferring is held at zero by writing the Integrity and HIL client against an
  abstract transport, so a simulator drops in later without touching a test.

## Settled

Conclusions from `design.md` that constrain everything above. Pointers, not
restatements: two copies of a decision means one of them is wrong. Wiring facts
are in `notes.md`.

- Motion runs on STEP/DIR from the ESP32. UART is configuration and telemetry
  only, and `VACTUAL` is a test path and an assert. §0
- 23 of 24 registers reachable, 10 configured, `OTP_PROG` left out entirely and
  reachable only by hand-assembled passthrough. §1
- StallGuard is for runtime tension sensing, not homing. The reels have no hard
  stop, so there is no zero to home to. §1
- Registers classify by who can change them: `VOLATILE` (the silicon, so poll),
  `OWNED` (the firmware, so cache), `CONSTANT` (nobody, so read once). Cache by
  ownership, never by cost. §2
- State is not a value. Values are read from cache, conditions are polled off
  the wire, and the distinction lives in the verb rather than in a flag. §2
- No defaults. All ten `OWNED` registers must be supplied, because the datasheet
  reset values for `GCONF` and `CHOPCONF` are properties of OTP bits and address
  straps rather than of the part. §7 item 7
- One shared single-wire UART, addresses strapped 0/1/2. Echo verified rather
  than merely discarded, reads sized exactly rather than slept for. §5
- Six inherited defects in `cinescaner-drive` recorded so they are not ported,
  plus one found in our own first pass. §7
