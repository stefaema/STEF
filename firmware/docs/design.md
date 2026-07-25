# Firmware design: the TMC2209 control stack

> Resolves the **Design** item in `roadmap.md`. Everything under
> *Implementation* there is downstream of the decisions below.
>
> Wiring facts live in `notes.md`; the code is
> `src/components/tmc2209/`.

---

## 0. Introduction

**The ESP32 owns motion. The UART carries configuration and telemetry. Driver actuates**

The subsystem, ignoring power: three driver boards, one motor each. All three
share **one UART bus**. Each also gets its **own STEP, DIR, EN and DIAG**
lines from the carrier. So UART traffic is addressed and serialized, while
the dedicated pins are per-driver and simultaneous.

### Address and microstepping conflict

- Sharing the bus means each driver needs a **distinct address**.
- The address is strapped on pins **MS1/MS2**.
- Those same pins otherwise select **microstep resolution**, so the two uses
  collide.
- We resolve it by disabling pin-based microstep selection: **`GCONF.mstep_reg_select
  = 1`**, after which `CHOPCONF.mres` decides. You just have to make sure of configuring the register for each driver before firing.

### Ways ESP32 communicates with TMC2209

- **Configuration and probing.** Reading and writing registers over UART.
  Structured, addressed, never time-critical.
- **Coordinated motion** (a.k.a. externally clocked). The ESP32 decides when
  each step happens and in which direction, on the STEP/DIR pins. Per driver,
  so three motors can move at once and in a fixed relationship to each other.
- **Independent motion** (velocity). Write a speed to `VACTUAL` and the
  driver generates its own steps at that rate until told otherwise. The right
  mode for **prolonged motion** where exact step count does not matter.

Beware: **a non-zero `VACTUAL` overrides the STEP
input**, silently, with no flag or fault. Since STEP/DIR is per-driver and
always physically present, a value left behind after a rewind leaves that one
driver deaf to its own STEP line while the other two still obey. So returning
to coordinated motion means writing `VACTUAL = 0` first, and that is an
asserted precondition rather than a convention.

### About position

A stepper is open loop: nothing measures the shaft.

- Under **independent motion** the driver generates the steps, so we cannot
  count them. There is no position.
- Under **coordinated motion** we emit every pulse, so counting them gives a
  position.
- But that count is a belief, not a measurement. Friction, tension or a jam
  can make the motor miss steps it was told to take, and nothing reports it.

So the system is open loop, with **StallGuard the only feedback** the driver
offers about what is physically happening.

### `TSTEP`

`TSTEP` is the driver's own measurement of the time between the microsteps it
*receives*, reported over UART. It is a period, not a rate: bigger means
slower.

Two uses:

- STEP is a one-way wire, so nothing otherwise tells the ESP32 whether pulses
  are arriving. Pulse at a known rate, read `TSTEP`, and a match proves the
  whole path works.
- `TPWMTHRS` and `TCOOLTHRS` are speed thresholds that the chip compares
  against `TSTEP`, in the same units. Reading `TSTEP` at a known speed is how
  those get set by measurement instead of arithmetic.

---

## 1. Register set

Two different questions get answered here, and they must be kept apart.

**Access is the chip's**, and it matters more than it looks: eight of these
registers are **write-only in silicon**. There is no read-back path. That
single fact decides §2.

**Decision is ours**, and it only says what the firmware *configures*. A
register we never configure is still reachable: raw RPC can read anything the
chip can read, so the PC-side diagnostic sees the whole device without
hand-assembling passthrough datagrams. "Read-only" below therefore means "no
field codecs, never written, never reflushed", not "unreachable".

| Register | Addr | Access | What it is | Decision |
|---|---|---|---|---|
| `GCONF` | 0x00 | RW | Global mode flags: UART enable, microstep source, direction invert, chopper mode | **Keep.** Where `pdn_disable` and `mstep_reg_select` get set; `shaft` flips a motor wired backwards without touching the harness. |
| `GSTAT` | 0x01 | R/WC | Three latched fault flags: reset, driver error, charge-pump undervoltage | **Keep.** `reset` is how we learn the driver browned out and lost its config. |
| `IFCNT` | 0x02 | R | Counts write datagrams the driver accepted. Wraps at 255 | **Keep.** A write gets no reply, so this is the only acknowledgement that exists. |
| `SLAVECONF` | 0x03 | **W** | `senddelay`: how long the driver waits before answering | **Keep.** Must be non-zero so the master can release a shared line before the reply starts. |
| `IOIN` | 0x06 | R | Live state of the input pins, plus a chip version byte | **Keep.** The pin states confirm wiring at bring-up, and the version byte identifies the silicon when a diagnostic wants to know. |
| `FACTORY_CONF` | 0x07 | RW | Factory-trimmed oscillator frequency and overtemperature thresholds | **Keep, read-only.** Reading tells us the trim. Writing detunes every timing-derived value. See §6. |
| `IHOLD_IRUN` | 0x10 | **W** | Run current, standstill current, and the ramp between them | **Keep.** Sets motor torque, and `ihold` is what holds film tension at rest. |
| `TPOWERDOWN` | 0x11 | **W** | Delay from standstill before dropping to hold current | **Keep.** Must be at least 2 or StealthChop auto-tuning never runs. |
| `TSTEP` | 0x12 | R | Measured time between the microsteps the driver receives | **Keep.** Our only proof that STEP pulses are arriving at all. See §0. |
| `TPWMTHRS` | 0x13 | **W** | Speed at which the chopper switches StealthChop to SpreadCycle | **Keep.** Quiet at scan speed, torque at rewind speed. |
| `TCOOLTHRS` | 0x14 | **W** | Lower speed bound for CoolStep and StallGuard | **Keep.** StallGuard reports nothing outside this window, so tension sensing depends on it. |
| `VACTUAL` | 0x22 | **W** | Internal velocity generator. Non-zero takes over from the STEP pin | **Keep.** The independent motion mode: rewind, spooling. Asserted zero before coordinated moves. See §0. |
| `SGTHRS` | 0x40 | **W** | Load level at which the driver calls a stall | **Keep.** The trip point for jam and film-break detection. |
| `SG_RESULT` | 0x41 | R | Continuous load estimate from back-EMF. Higher means less load | **Keep.** The tension signal itself. |
| `COOLCONF` | 0x42 | **W** | CoolStep: automatic current reduction while load is low | **Keep.** Less heat on a lightly loaded reel, which matters on three motors running for a whole reel. |
| `MSCNT` | 0x6A | R | Position within the driver's internal sine table, 0 to 1023 | **Keep, provisionally.** Electrical phase, not machine position. Cheap to carry; no concrete use has survived scrutiny yet. |
| `CHOPCONF` | 0x6C | RW | Chopper timing, sense-resistor scale, and microstep resolution | **Keep.** `mres` is the resolution we took away from MS1/MS2; `vsense` picks the current range. |
| `DRV_STATUS` | 0x6F | R | Overtemperature, short and open-load flags, actual current, standstill | **Keep.** Our only fault channel. |
| `PWMCONF` | 0x70 | RW | StealthChop PWM amplitude and gradient tuning | **Read-only.** `pwm_autoscale` and `pwm_autograd` tune these better than we would and are on by default. Readable so the diagnostic can show what they chose. |
| `PWM_SCALE` | 0x71 | R | The amplitude StealthChop actually settled on | **Read-only.** Tuning telemetry; no firmware decision depends on it. |
| `PWM_AUTO` | 0x72 | R | The offset and gradient auto-tuning arrived at | **Read-only.** Same. |
| `MSCURACT` | 0x6B | R | The sine-table entries for the microstep position the driver is presently at, one per phase. **Not a measurement** | **Read-only.** A pure function of `MSCNT`, so it carries no new information, but it is free to expose and the 9-bit signed fields are worth a decoder. |
| `OTP_READ` | 0x05 | R | Reads back the one-time-programmed bits | **Read-only.** Nothing acts on it while we never program them. |
| `OTP_PROG` | 0x04 | W | Burns one-time-programmable fuses into the chip | **Absent entirely.** Irreversible, and we configure over UART anyway. Reaching it means hand-assembling a passthrough datagram, which is the right amount of friction. |

The configurable set is
what `reflush()` imposes; everything else is readable and never written.

### On StallGuard

We are using StallGuard for **runtime tension sensing, not homing**. Homing
means finding a known zero on a bounded axis by driving into a hard stop.
Our reels rotate continuously and have no hard stop, so there is no zero to
find, and frame position comes from vision regardless.

What load sensing does buy us:

- **Reel diameter changes as film winds.** Constant RPM on the takeup means
  linear speed climbs as the roll grows. Without feedback the film tightens
  until it stretches.
- **Jam and splice detection**, before brittle archival stock tears.
- **End of reel or film break**, where load collapses.

`SG_RESULT` is speed-dependent, needs per-motor calibration, is only valid
inside the `TCOOLTHRS` window, and is junk near standstill. It is a real
signal, not a free one.

---

## 2. State

In order to have a stateful system the **shadow register file** is introduced: one `uint32_t` slot per kept
register, plus a dirty bitmap. Carrying 23 registers keeps that bitmap inside
a single `uint32_t`, which is the practical cap on how many we can add.

- Write-only registers become readable *from the shadow*, which is the only
  honest way to answer "what is `IHOLD_IRUN` set to?"

- A flush writes only what changed, so a cadence-critical path costs one
  datagram instead of five.
- `GSTAT.reset` set means the shadow is stale: re-flush everything.

The one rule the shadow imposes: **never present a shadow value and a
device-read value in the same view without labelling them.** Shadow is
*commanded*, a read is *actual*. The API enforces this by naming: 
`tmc2209_read()` hits the wire, `tmc2209_shadow()`
does not, and you cannot confuse them at a call site.

### The trust bit

`dirty` is not enough. It says "the shadow holds a value the device has not
received yet", which is repairable by writing that one register. A second,
worse failure exists: **the device may hold values the shadow never issued.**
Three things cause it, and they collapse onto one flag and one recovery.

| Cause | Why the shadow stops being true |
|---|---|
| fresh construction | nothing has been imposed on the device yet |
| `GSTAT.reset` | the driver browned out and lost its configuration |
| RPC passthrough | bytes we did not build, deliberately uninterpretable |

Recovery is `reflush()` in all three cases, because **you cannot repair the
shadow by reading**: eight registers are write-only.

`tmc2209_shadow()` returns `ERR_STALE` while untrusted rather than handing
back a plausible-looking number. A shadow that lies quietly is worse than no
shadow.

### Execution Modes

Three ways the PC can reach a driver, at three levels of abstraction. They map
onto the three layers of §3, which is a good sign the layering is real.

| RPC mode | Talks to | Description | Effect on the shadow |
|---|---|---|---|
| smart | `actuator` | The PC asks for an outcome, "takeup at 30 RPM", and the actuator works out which registers and pulse rate that implies. | Stages and flushes, stays true. |
| raw | `tmc2209_t` | The PC names a register and a value. Framing, CRC and verification still ours. | Goes through `tmc2209_write()`, so it **updates the shadow by construction**. |
| passthrough | `tmc2209_bus_t` | The PC supplies the datagram bytes and gets the reply verbatim. Nothing is interpreted, which is exactly what direct driver testing needs. | The only one that can desync, since we cannot account for bytes we did not build (trust bit covers it). |

---

## 3. Layering

| Component | Owns | Knows nothing about |
|---|---|---|
| `tmc2209` | UART framing, CRC, shadow registers, register semantics | ESP-IDF, GPIO, time |
| `stepgen` | STEP/DIR/EN timing on ESP32 peripherals | Registers, UART |
| `actuator` | One of each (`feed`, `capstan`,`takeup`), plus calibration (WIP). Enforces `VACTUAL == 0` when needed. Turns "takeup, 30 RPM" into pulses plus the current and microstep config behind them | control policy |

### The port

The library's only output is bytes. A `tmc2209_port_t` supplies `tx`, `rx`,
optional `purge_rx`, optional `lock`/`unlock`, an optional `trace` hook, and
an `echoes` flag. Three backends fall out: ESP-IDF wrapping `uart_read_bytes`
(`echoes = true`), the PC-side SIL link (`echoes = false`, full duplex), and
the unit-test mock.

Note what is absent: **there is no clock**. Timeouts pass down as a
millisecond count and the port decides how to wait. That is what keeps the
core free of ESP-IDF and lets the unit tests run instantly instead of
sleeping. Consequence: retries are immediate, with no backoff. On a
one-metre bus with three nodes that is fine; if it ever is not, the fix is a
delay hook, not a clock.

### Ownership and concurrency

**Two separate transports**, which is easy to conflate and worth stating:

```
PC ──USB Serial/JTAG──> [rpc task] ──queue──> [control task] ──UART1──> TMC bus ──> 3 drivers
                                                    │
                                                    └── stepgen (RMT) ──STEP/DIR──> drivers
```

The PC link is native USB, already the console. The TMC bus is a UART. No
contention on the wire; UART2 stays free.

**One control task owns the TMC bus and all three devices.** RPC posts
requests into its queue rather than reaching the bus itself. The contention
being avoided is not the wire, it is the *transaction sequence*: an RPC task
answering on its own schedule lands between the control loop's read and the
decision based on it.

Three actuators are not three independent controllers, because **the film
physically couples them**. Tension at the takeup is a function of what the
capstan does, and tension only exists *between* motors, so the loop has to see
all three. Step generation is hardware, so the loop only does slow outer
control at 50-200 Hz, and §5's arithmetic gives ~300 Hz for all three
round-robin. The bus cadence and the control cadence are the same cadence;
concurrency would buy no throughput, only nondeterminism.

So the library is **not thread-safe by design**: one device, one owner. The
port's `lock`/`unlock` hooks stay NULL on target and exist for the PC-side
harness. A side effect worth having: the control task owns stepgen too, so
`VACTUAL == 0` is guaranteed by construction rather than defensively asserted.

---

## 4. Transport rules

**Echo.** TX and RX are joined at the carrier (§5), so every transmitted byte
comes back on RX. Discard exactly the echoed length before parsing a reply.

**Read block.** Use a thing like
`uart_read_bytes(port, buf, 12, timeout_ticks)`, which blocks until exactly
12 bytes or a timeout.

**`SLAVECONF.senddelay` must be non-zero.** A shared bus needs the slave to
wait before replying so the master can release the line.

**The echo is evidence, not litter.** Tempting to discard it in the ESP32
backend, but a mismatch between what went out and what came back means
something else drove the line while we were talking. It is the cheapest
bus-collision detector we have, so echo verification lives in the library
where it is testable, and `echoes = false` covers full-duplex backends.

**Every write is verified.** A write datagram gets no reply, so `IFCNT` is
the only acknowledgement available. This should not be optional.

Checking one write means reading `IFCNT` and expecting it one higher than we
last saw it. Done per register, a ten-register flush costs ten writes and ten
reads. So **`flush()` checks the batch instead**: ten writes, then one read
expecting ten more. Eleven transactions rather than twenty. A single
`tmc2209_write()` still confirms on the spot.

The expected increase is a **range, not an exact number**, because a retried
write may have landed twice: an attempt whose echo came back corrupted can
still have reached the driver and been counted. Rewriting a register with the
same value leaves the same state, so anything between "each register landed
once" and "every datagram sent was counted" passes.

One consequence, since verification compares against a remembered value:
**`flush()` re-reads `IFCNT` first whenever the shadow is untrusted.** A
passthrough write bumps the chip's counter without passing through here, and
verifying against a baseline we cannot vouch for would fail the very
operation that exists to recover.

**Every read is CRC-checked**, and a mismatch retries rather than failing
straight out. But a reply for the *wrong register* does not retry: it means a
second driver answered, which no number of attempts will fix. One wedged
driver must not stall the other two: per-transaction timeout, bounded
retries, then fault the actuator.

**`GSTAT.reset` is polled.** Set means the driver lost its configuration and
the shadow is fiction until re-flushed.

---

## 5. Bus and wiring

**One shared single-wire UART for all three drivers**, addresses strapped
0/1/2 on MS1/MS2 per driver board.

The RJ45 cable carries the same eight conductors either way, so separate
UARTs buy no cable saving, and they would consume all three of the S3's
UARTs with zero spare. Bandwidth is not close to a constraint: at 115200 a
read transaction is roughly 1.1 ms, so round-robin polling of three motors
runs at ~300 Hz, and the TMC2209 auto-detects baud from the sync byte, so
500k is available if we ever want it. The accepted cost is that a wedged
driver can hold the line, which the §4 timeout and retry rules contain.

Full pinout, straps, and board-level gotchas live in **`notes.md`**, under
*Hardware interface*. They are wiring facts, not design decisions, and this
document should not be where you go looking for a pinout.

---

## 6. Inherited defects: do not port these

Found in `cinescaner-drive` while deciding the above. Listed so the C
implementation does not reproduce them, and so the Python lib can be fixed
if it stays in service as the PC-side diagnostic.

1. **`scheme.py` and `registers.py` are byte-identical**, 654 lines each.
   Nothing imports `scheme`. Dead file.
2. **`push_base()` writes `FACTORY_CONF`**, which defaults to `fclktrim=0`.
   That overwrites the factory oscillator trim on every init, so every
   timing-derived quantity (`TSTEP`, `TPWMTHRS`, `TCOOLTHRS`, StealthChop
   frequency) drifts. This is why `FACTORY_CONF` is read-only for us.
3. **Reading write-only registers.** See §2. `pull_motion()` in full, plus
   `SLAVECONF` in `pull_base()`, plus the same registers in `probe.py`,
   whose report is therefore part fiction.
4. **Writes are never verified.** `read_ifcnt()` exists and nothing calls it.
5. **The read-timing hack.** See §4.
6. Minor: `self._vactual` is written and never read; `RegisterAddress` is
   imported unused in `tmc2209.py`; `pull_base`/`pull_motion` re-import
   module-level names locally; `__pycache__` is tracked in git.

---

## 7. Deferred, on purpose

- **`PWMCONF` tuning.** Reset defaults plus autoscale until measurement says
  otherwise.
- **Per-actuator profiles.** Feed, capstan and takeup will not share current
  or StallGuard calibration, but the shape of that config is not worth
  guessing before Phase 2 hardware exists.
- **Any use for `MSCNT`.** The register is cheap enough to keep, but what it
  reports is electrical phase, not machine position, and no use for that has
  survived scrutiny yet. Revisit if a concrete need appears.
