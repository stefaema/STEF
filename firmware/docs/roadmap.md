# Firmware roadmap

## Design

[DONE] Settled in `design.md`. What came out of it:
- Motion runs on STEP/DIR from the ESP32; UART is configuration and
  telemetry only. `VACTUAL` is a test path and an assert.
- 23 of 24 registers reachable, but only 10 configured, and `OTP_PROG` left
  out entirely. StallGuard is for **runtime tension sensing**,
  not homing: the reels have no hard stop, so there is no zero to home to.
- The Base/Motion config split **does not survive**. Replaced by a register
  cache, which is the only honest way to represent the eight registers that
  are write-only in silicon.
- Registers are classified by **who can change them**: `VOLATILE` (the
  silicon, so poll), `OWNED` (the firmware, so cache), `CONSTANT` (nobody, so
  read once). Cache by ownership, never by cost.
- **State is not a value.** Values are read from cache, conditions are polled
  off the wire, and the distinction lives in the verb rather than a flag.
- One shared single-wire UART, addresses strapped 0/1/2. Echo verified, not
  merely discarded; reads sized exactly, not slept for.
- Six inherited defects in `cinescaner-drive` recorded so we don't port
  them, plus one found in our own first pass. Wiring facts are in `notes.md`.

## Implementation

Layering is fixed by `design.md` §4:
- **Library** (`tmc2209`): [in progress] `src/components/tmc2209/`. Framing,
  CRC, echo verification, IFCNT-verified writes and passthrough are done and
  tested. Zero dependencies, not even ESP-IDF, so it compiles natively for the
  unit tier. The API is being reworked to the design in `design.md` §3:
  - register table gains the `VOLATILE`/`OWNED`/`CONSTANT` class column, and
    loses the reset-value column (see §7 item 7)
  - `stage`/`recall`/`flush`/`impose` collapse into batch `write()` and
    cached `read()`
  - `poll_health`/`poll_load`/`poll_pins`/`poll_raw` replace raw telemetry
    reads; `identify`/`verify_config` added
  - `set_velocity`/`set_current` for the two runtime writes
  - dirty bitmap and trust bit collapse into one validity bitmap
- **`stepgen` / `actuator`**: [next] STEP/DIR/EN timing, and the layer that
  owns one of each plus calibration, and enforces the `VACTUAL == 0`
  precondition. Three of them: `feed`, `capstan`, `takeup`. Not "axis": these
  rotate continuously and have no bounded travel to home to.
- **Firmware**: talks to the ESP32 from the PC and awaits responses, the
  RPC layer. Uses the library internally, doesn't duplicate protocol logic.
- **Software**: there'll be a daemon that keeps direct comm with the controller, and this software can be prod or test-scoped. See test.

## Test

Named for the tiers themselves, not for "host", which already means the PC in
these docs.

- **Unit** (`test/unit/`): [rework pending] 67 Unity tests, natively compiled,
  no ESP32. The transport and framing tests stand; the device tests follow the
  API rework above. Note that the existing suite could not catch §7 item 7,
  because it asserted the device matched the cache and the cache was the bug.
  Classification and configuration-coverage assertions are what close that gap.
  Runs against a mock that models the device rather than replaying scripted
  bytes, so tests read as "the register should now hold X". Fault injection
  covers CRC corruption, echo corruption, silence, wrong-register replies and
  uncounted writes. CRC vectors come from the Python lib that ran on real
  silicon, so passing means agreeing with hardware, not with ourselves.
  ```
  cmake -S firmware/test/unit -B build-unit && cmake --build build-unit
  ctest --test-dir build-unit --output-on-failure
  ```
- **Integration, SIL** (`test/sil/`): PC-side robust TMC2209 simulator behind
  the same `tmc2209_port_t`. Firmware transport may differ here (e.g. USB
  instead of pin-based UART) to make PC-to-simulator easier; the port's
  `echoes = false` covers that.
- **Integration, HIL** (`test/hil/`): PC host explicitly runs in HIL mode, real
  driver(s), maybe real motors. Driven through RPC passthrough mode, which is
  what `tmc2209_bus_xfer()` exists for. Possible physical validation (e.g.
  confirm actual motor rotation), not decided yet.
