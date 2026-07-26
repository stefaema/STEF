# Firmware design: the TMC2209 control stack

> Resolves the **Design** item in `roadmap.md`. Everything under
> *Implementation* there is downstream of the decisions below.
>
> Wiring facts live in `notes.md`; the code is
> `src/components/tmc2209/`.

---

## 0. Introduction

**The ESP32 owns motion. The UART carries configuration and telemetry. The
driver actuates.**

The subsystem, ignoring power: three driver boards, one motor each. All three
share **one UART bus**. Each also gets its **own STEP, DIR, EN and DIAG**
lines from the carrier. UART traffic is therefore addressed and serialized,
while the dedicated pins are per-driver and simultaneous.

### Address and microstepping conflict

Sharing the bus means each driver needs a distinct address, and the address is
strapped on pins **MS1/MS2**. Those same pins otherwise select **microstep
resolution**, so the two uses collide.

The conflict is resolved by disabling pin-based microstep selection.
`GCONF.mstep_reg_select = 1` moves resolution to `CHOPCONF.mres`. Until that
write lands, the three drivers run at whatever resolution their address straps
selected, which is a different resolution per driver. No STEP pulses may be
issued before configuration completes.

### Three ways the ESP32 reaches a driver

- **Configuration and probing.** Reading and writing registers over UART.
  Structured, addressed, never time-critical.
- **Coordinated motion** (a.k.a. externally clocked). The ESP32 decides when
  each step happens and in which direction, on the STEP/DIR pins. Per driver,
  so three motors can move at once and in a fixed relationship to each other.
- **Independent motion** (a.k.a. internally clocked, velocity mode). A speed
  written to `VACTUAL` makes the driver generate its own steps at that rate
  until told otherwise. This is the mode for prolonged motion where exact step
  count does not matter, such as rewind and spooling.

A non-zero `VACTUAL` **overrides the STEP input**, with no flag and no fault
raised. STEP/DIR is per-driver and always physically present, so a value left
behind after a rewind leaves that one driver deaf to its own STEP line while
the other two still obey. Returning to coordinated motion therefore requires
writing `VACTUAL = 0` first. §4 assigns enforcement of that precondition to the
actuator layer.

One consequence of §1: `VACTUAL` is write-only in silicon, so the precondition
can only ever be checked against the firmware's own record of what it wrote.
That record is authoritative under the ownership rule in §2, but its
authority ends the moment the driver resets, which is why `DRIVER_RESET` is a
fault rather than a cache miss.

### About position

A stepper is open loop: nothing measures the shaft.

- Under independent motion the driver generates the steps, so the firmware
  cannot count them. There is no position.
- Under coordinated motion the firmware emits every pulse, so counting them
  yields a position.
- That count is an estimate, not a measurement. Friction, tension or a jam can
  make the motor miss steps it was told to take, and nothing reports the loss.

StallGuard is the only feedback the driver offers about what is physically
happening.

### `TSTEP`

`TSTEP` is the driver's own measurement of the time between the microsteps it
*receives*, reported over UART. It is a period, not a rate: a larger value
means slower.

It has two uses. STEP is a one-way wire, so nothing otherwise tells the ESP32
whether pulses are arriving; pulsing at a known rate and reading `TSTEP` back
proves the whole path works. Separately, `TPWMTHRS` and `TCOOLTHRS` are speed
thresholds the chip compares against `TSTEP` in the same units, so reading
`TSTEP` at a known speed sets those by measurement rather than arithmetic.

Both uses require a working step generator, so both are deferred with
`stepgen`. See §8.

---

## 1. Register set

Two independent questions are answered here and must be kept apart: what the
*silicon* permits, and what the *firmware* does.

**Access is the chip's.** Eight registers are write-only in silicon, with no
read-back path at all. That fact drives all of §2.

**Class is ours, but it describes physics rather than policy.** Each register
is classified by *who is able to change its value*, because that determines
whether a remembered value is still true:

| Class | Who mutates it | Consequence |
|---|---|---|
| `VOLATILE` | the silicon or the outside world | must be polled; never cached |
| `OWNED` | the firmware, and nothing else | cacheable for as long as the cache is valid |
| `CONSTANT` | nothing, in this design | read once at adopt, cached from then on |

The classification is a physical property of the part, not a performance
judgement. `GSTAT` is never cacheable no matter how often it is read, and
`VACTUAL` is always cacheable even though the chip refuses to read it back.
The rule is: **cache by ownership, never by cost.**

`OWNED` is exactly the set the firmware configures. `CONSTANT` registers are
readable and never written. `VOLATILE` registers are readable and never
written except for `GSTAT`, whose write path clears latched flags rather than
setting configuration.

| Register | Addr | Silicon | Class | What it is | Policy |
|---|---|---|---|---|---|
| `GCONF` | 0x00 | RW | `OWNED` | Global mode flags: UART enable, microstep source, direction invert, chopper mode | Carries `pdn_disable` and `mstep_reg_select`, both required. `shaft` flips a motor wired backwards without touching the harness. |
| `GSTAT` | 0x01 | R/WC | `VOLATILE` | Three latched fault flags: reset, driver error, charge-pump undervoltage | Reported through `poll_health()`. Cleared at adopt, and thereafter by `clear_faults()`. |
| `IFCNT` | 0x02 | R | `VOLATILE` | Counts write datagrams the driver accepted. Wraps at 255 | Internal. The only acknowledgement a write can get. See §5. |
| `SLAVECONF` | 0x03 | W | `OWNED` | `senddelay`: how long the driver waits before answering | Must be non-zero so the master can release a shared line before the reply starts. |
| `IOIN` | 0x06 | R | `VOLATILE` | Live state of the input pins, plus a chip version byte | Pin states confirm wiring at bring-up through `poll_pins()`. The version byte is reported by `poll_version()`. |
| `FACTORY_CONF` | 0x07 | RW | `CONSTANT` | Factory-trimmed oscillator frequency and overtemperature thresholds | Never written. Writing it detunes every timing-derived value; see §7. Read at adopt because the trim differs per part. |
| `IHOLD_IRUN` | 0x10 | W | `OWNED` | Run current, standstill current, and the ramp between them | Sets motor torque. `ihold` holds film tension at rest. Adjusted at runtime through `set_current()`. |
| `TPOWERDOWN` | 0x11 | W | `OWNED` | Delay from standstill before dropping to hold current | Must be at least 2 or StealthChop auto-tuning never runs. |
| `TSTEP` | 0x12 | R | `VOLATILE` | Measured time between the microsteps the driver receives | Deferred with `stepgen`. See §0. |
| `TPWMTHRS` | 0x13 | W | `OWNED` | Speed at which the chopper switches StealthChop to SpreadCycle | Quiet at scan speed, torque at rewind speed. |
| `TCOOLTHRS` | 0x14 | W | `OWNED` | Lower speed bound for CoolStep and StallGuard | StallGuard reports nothing outside this window, so tension sensing depends on it. |
| `VACTUAL` | 0x22 | W | `OWNED` | Internal velocity generator. Non-zero takes over from the STEP pin | Independent motion: rewind, spooling. Written through `set_velocity()`. See §0. |
| `SGTHRS` | 0x40 | W | `OWNED` | Load level at which the driver calls a stall | The trip point for jam and film-break detection. |
| `SG_RESULT` | 0x41 | R | `VOLATILE` | Continuous load estimate from back-EMF. Higher means less load | The tension signal. Reported through `poll_load()`. |
| `COOLCONF` | 0x42 | W | `OWNED` | CoolStep: automatic current reduction while load is low | Less heat on a lightly loaded reel, which matters across three motors running a whole reel. |
| `MSCNT` | 0x6A | R | `VOLATILE` | Position within the driver's internal sine table, 0 to 1023 | Diagnostic only. Electrical phase, not machine position. |
| `CHOPCONF` | 0x6C | RW | `OWNED` | Chopper timing, sense-resistor scale, and microstep resolution | `mres` is the resolution taken away from MS1/MS2; `vsense` picks the current range. |
| `DRV_STATUS` | 0x6F | R | `VOLATILE` | Overtemperature, short and open-load flags, actual current, standstill | The fault channel. Reported through `poll_health()`. |
| `PWMCONF` | 0x70 | RW | `CONSTANT` | StealthChop PWM amplitude and gradient tuning | Never written: `pwm_autoscale` and `pwm_autograd` tune it better and are on by default. Constant because nothing else writes it either. |
| `PWM_SCALE` | 0x71 | R | `VOLATILE` | The amplitude StealthChop actually settled on | Diagnostic only. |
| `PWM_AUTO` | 0x72 | R | `VOLATILE` | The offset and gradient auto-tuning arrived at | Diagnostic only. |
| `MSCURACT` | 0x6B | R | `VOLATILE` | The sine-table entries for the present microstep position, one per phase. **Not a measurement** | Diagnostic only. A pure function of `MSCNT`, so it carries no new information, but the 9-bit signed fields are worth a decoder. |
| `OTP_READ` | 0x05 | R | `CONSTANT` | Reads back the one-time-programmed bits | Never acted on while the fuses are never programmed. Read at adopt because the values differ per part. |
| `OTP_PROG` | 0x04 | W | absent | Burns one-time-programmable fuses into the chip | **Not in the table.** Irreversible, and configuration goes over UART anyway. Reaching it requires a hand-assembled passthrough datagram. |

Totals: 10 `VOLATILE`, 10 `OWNED`, 3 `CONSTANT`.

A register being outside the `OWNED` set does not make it unreachable. Raw
transport can read anything the chip can read, so the PC-side diagnostic sees
the whole device without hand-assembling datagrams.

### Reset values are not in this table

An earlier version of the register table carried a reset-value column, seeded
into the cache at construction. That is removed, for two reasons.

The first is correctness. Two of the values are not properties of the part
number. `GCONF`'s reset value depends on OTP bits, so the datasheet figure is
a factory default rather than a guarantee, and `CHOPCONF` boots with a
resolution selected by the address straps, which differs per driver. Recording
either as a constant states more than is known.

The second is that a seeded default is a value the firmware will eventually
write. `adopt()` imposes the cache, so seeding the cache with datasheet
defaults means adopting a fresh driver writes `mstep_reg_select = 0`, undoing
the one setting §0 is built around. See §7.

`OWNED` registers therefore start with no value at all, and a configuration
that does not cover all ten is rejected rather than completed from defaults.

### On StallGuard

StallGuard is used for **runtime tension sensing, not homing**. Homing means
finding a known zero on a bounded axis by driving into a hard stop. The reels
rotate continuously and have no hard stop, so there is no zero to find, and
frame position comes from vision regardless.

Load sensing buys three things:

- **Reel diameter changes as film winds.** Constant RPM on the takeup means
  linear speed climbs as the roll grows. Without feedback the film tightens
  until it stretches.
- **Jam and splice detection**, before brittle archival stock tears.
- **End of reel or film break**, where load collapses.

`SG_RESULT` is speed-dependent, needs per-motor calibration, is only valid
inside the `TCOOLTHRS` window, and is meaningless near standstill.

---

## 2. State: the register cache

Eight registers are write-only in silicon. "What is `IHOLD_IRUN` set to?" is
therefore a question the device cannot answer, and it is a question the
actuator layer needs answered on every control iteration. The only possible
source is the firmware's own record of what it wrote.

That record is a **cache of one `uint32_t` per register**, and §1's
classification decides what may be served from it. `OWNED` and `CONSTANT`
reads come from memory. `VOLATILE` reads always go to the wire, because a
remembered fault flag or load estimate describes a moment that has passed.

Carrying 23 registers keeps the validity bitmap inside a single `uint32_t`,
which is the practical cap on how many can be added.

### Validity

Each slot is in one of two states:

| State | Meaning |
|---|---|
| `UNKNOWN` | the device's value is not derivable from anything recorded here |
| `SYNCED` | the device holds what this slot says |

There is no third state for "written but not yet sent", because §3 makes the
batch the unit of writing: there is no interval during which the cache holds
a value the device has not been offered.

A slot becomes `SYNCED` when a write to it is confirmed, or, for `CONSTANT`
registers, when it is read off the part at adopt. Every `OWNED` slot returns
to `UNKNOWN` in three situations:

| Cause | Why the record stops being true |
|---|---|
| fresh construction | nothing has been written to the device yet |
| `DRIVER_RESET` from `poll_health()` | the driver browned out and lost its configuration |
| raw transport | bytes the library did not build, deliberately uninterpreted |

`tmc2209_trusted()` is the derived query "no `OWNED` slot is `UNKNOWN`". It is
not stored.

### Recovery is not the library's job

The library cannot repair the cache by reading, because eight of the registers
have no read path. It also does not re-impose from memory, because it is not
the owner of the configuration. The PC, or an aggregating task on the ESP32,
holds the configuration and re-sends it.

That is a deliberate narrowing. A driver that reset mid-reel has lost more
than its registers: it has lost `VACTUAL`, and with it any position estimate
built on the assumption that STEP pulses were being obeyed. Treating that as a
cache miss to paper over would hide a mechanical event. `DRIVER_RESET` is
surfaced as a fault condition, the actuator layer decides what to do, and
reconfiguration is an ordinary batch write afterwards.

Reconfiguring unconditionally at every bring-up is cheap, roughly eleven
transactions, and is preferred to any scheme that tries to detect whether it
is necessary.

### State is not a value

A register whose value the firmware sets is a value: it can be held, recalled
and compared. A register the silicon sets is a *condition*: what matters is
whether it currently holds, and a copy of it from a second ago answers a
question nobody asked.

This is why the API in §3 does not offer a uniform read over all 23 registers.
Values are read. Conditions are polled. The distinction is carried in the verb
rather than in a parameter, so it cannot be got wrong at a call site, and
changing a register's class becomes a compile error rather than a silent
change in blocking behaviour.

---

## 3. The API

Three families, distinguished by what they do rather than by which register
they touch.

### Values: `read` and `write`

```c
tmc2209_err_t tmc2209_read (tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);
tmc2209_err_t tmc2209_write(tmc2209_t *dev,
                            const tmc2209_regval_t *ops, size_t n,
                            size_t *failed_at);
```

`read()` serves `OWNED` and `CONSTANT` registers from the cache and never
touches the bus. `ERR_STALE` if the slot is `UNKNOWN`, `ERR_ACCESS` for a
`VOLATILE` register, which has no cached value by construction.

`write()` takes a batch. The array is the unit of work, which is what removes
the need for a staging state, a dirty bitmap, and a separate flush. It also
matches the wire: n datagrams followed by one `IFCNT` verification, per §5.

Batch semantics:

- **Ordering.** Applied in order. A register appearing twice takes its last
  value, matching what the wire would do.
- **Skipping.** An op whose value already matches a `SYNCED` slot is dropped
  before transmission. A batch may therefore put zero datagrams on the wire.
  This recovers the "write only what changed" saving without any staging
  machinery.
- **Failure.** Any failure marks **every** slot in the batch `UNKNOWN`,
  including ops that were transmitted before the failure. Nothing in a batch
  is confirmed until the `IFCNT` read at the end, so an early abort leaves
  even the transmitted ops unverified. Recovery is to re-send the batch.
- **`failed_at`** is diagnostic only. It reports which op the library was on
  when it gave up, not where the state boundary is, and it is set to `n` on
  `ERR_NO_ACK`, where no single op is at fault.

### Conditions: `poll_*`

Every `poll_` call performs a transaction and returns meaning rather than
register contents.

```c
tmc2209_err_t tmc2209_poll_health(tmc2209_t *dev, uint32_t *conditions);
tmc2209_err_t tmc2209_poll_load  (tmc2209_t *dev, tmc2209_load_t *out);
tmc2209_err_t tmc2209_poll_pins  (tmc2209_t *dev, tmc2209_ioin_t *out);
tmc2209_err_t tmc2209_poll_raw   (tmc2209_t *dev, tmc2209_reg_t reg, uint32_t *out);
```

`poll_health()` reads both `GSTAT` and `DRV_STATUS` and returns a single
condition set: `DRIVER_RESET`, `DRIVER_FAULT`, `UNDERVOLTAGE`,
`OVERTEMP_WARNING`, `OVERTEMP_SHUTDOWN`, `SHORT_CIRCUIT`, `OPEN_LOAD`,
`STANDSTILL`. The caller asks whether the driver is healthy and never learns
that brownout and overtemperature live in different registers.

The set spans two different notions of time, and the caller has to know which
is which. The three `GSTAT` conditions are **latched**: they report that
something happened and stay asserted until acknowledged. The five `DRV_STATUS`
conditions are **live**: they report what is true now and clear themselves when
the situation passes. An overtemperature shutdown disappears once the chip
cools; an undervoltage does not.

`poll_health()` is purely observational, so polling twice yields the same
answer. That is what makes `clear_faults()` necessary:

```c
tmc2209_err_t tmc2209_clear_faults(tmc2209_t *dev, uint32_t conditions);
```

The caller hands back the conditions it received. Only the latched ones are
acted on, so passing the whole set is the intended use. Acknowledging exactly
what was seen is also what makes it safe against a flag that latches between
the poll and the acknowledgement: that flag was never reported, so it is not
cleared, and it survives to be reported next time.

Acknowledging does not restore trust. Clearing `DRIVER_RESET` states that the
reset was noticed, not that the configuration was rewritten; only a successful
`write()` over the owned registers does that. The two are deliberately separate,
because a driver that reset mid-reel needs the actuator layer to decide what
happens to the film before anything is written back to it.

Skipping the acknowledgement does not merely lose information. A single
brownout would assert `DRIVER_RESET` on every subsequent poll for the rest of
the session, and each poll would invalidate the configuration the previous
recovery had just written, so the loop never converges.

`poll_load()` returns the `SG_RESULT` estimate together with whether the
reading can be believed. The validity rule needs `TCOOLTHRS`, which is in
cache, and the current speed, which is not yet available; see §8. The first
implementation checks only whether `TCOOLTHRS` is zero, which means StallGuard
is disabled outright and the number is meaningless. That check costs nothing
and catches the most likely configuration mistake.

`poll_pins()` returns the decoded struct, because pin-level detail is exactly
what the caller is asking for at bring-up.

`poll_raw()` covers `MSCNT`, `MSCURACT`, `PWM_SCALE` and `PWM_AUTO`. §1 marks
all four diagnostic-only, so there is no condition to name and no decision
that depends on them. This is also the path a "dump every register" report
uses.

The library reports conditions and never decides responses. What
`GSTAT.reset` means is a fact about the chip. Whether it should fault the reel
or trigger a quiet reconfiguration is control policy, and lives above.

### Verdicts: `verify_*`

```c
tmc2209_err_t tmc2209_verify_config(tmc2209_t *dev, uint32_t *mismatched);
```

Performs transactions and returns a pass or fail rather than a number.
`verify_config()` re-reads the config registers the silicon will answer for,
`GCONF` and `CHOPCONF`, and reports which disagree with the cache. It exists
so the HIL tier can assert that the cache is telling the truth, which is the
test that validates the whole abstraction in §2. Nothing in the control path
calls it.

### Named runtime writes

```c
tmc2209_err_t tmc2209_set_velocity(tmc2209_t *dev, int32_t v);
tmc2209_err_t tmc2209_set_current (tmc2209_t *dev, const tmc2209_ihold_irun_t *c);
```

Two `OWNED` registers are written during motion rather than during
configuration: `VACTUAL` for independent motion, and `IHOLD_IRUN` for tension,
which §1 explains must track reel diameter continuously. Both go through the
same write funnel as a one-op batch, and both are named because a control loop
should not be assembling arrays and because §0's `VACTUAL` precondition
deserves to be visible at the call site.

### Lifecycle and raw transport

```c
tmc2209_err_t tmc2209_init (tmc2209_t *dev, const tmc2209_bus_t *bus, uint8_t addr);
tmc2209_err_t tmc2209_adopt(tmc2209_t *dev,
                            const tmc2209_regval_t *config, size_t n,
                            tmc2209_gstat_t *at_bringup);
bool          tmc2209_trusted (const tmc2209_t *dev);
void          tmc2209_distrust(tmc2209_t *dev);

tmc2209_err_t tmc2209_bus_xfer(const tmc2209_bus_t *bus,
                               const uint8_t *tx, size_t tx_len,
                               uint8_t *rx, size_t rx_len);
```

`adopt()` probes the driver, seeds the `IFCNT` baseline, clears `GSTAT` and
hands back its pre-clear value, reads the three `CONSTANT` registers off the
part, and writes the supplied configuration. It rejects a configuration that
does not cover all ten `OWNED` registers, which makes the defect in §7 item 7
structurally unreachable rather than merely fixed.

`bus_xfer()` moves bytes with no interpretation, keeping the lock and the echo
discipline. It is what the RPC passthrough mode and the HIL tier drive.
Callers that use it to write must call `distrust()`.

### Execution modes

Three ways the PC reaches a driver, mapping onto three layers of §4.

| Mode | Talks to | Description | Effect on the cache |
|---|---|---|---|
| smart | `actuator` | The PC asks for an outcome, "takeup at 30 RPM", and the actuator works out which registers and pulse rate that implies. | Writes through the library, stays valid. |
| raw | `tmc2209_t` | The PC names registers and values. Framing, CRC and verification are still the library's. | Goes through `write()`, so the cache stays valid by construction. |
| passthrough | `tmc2209_bus_t` | The PC supplies datagram bytes and gets the reply verbatim. Nothing is interpreted, which is what direct driver testing needs. | The only mode that can desync, since bytes the library did not build cannot be accounted for. Covered by `distrust()`. |

---

## 4. Layering

| Component | Owns | Knows nothing about |
|---|---|---|
| `tmc2209` | UART framing, CRC, the register cache, register semantics | ESP-IDF, GPIO, time |
| `stepgen` | STEP/DIR/EN timing on ESP32 peripherals | Registers, UART |
| `actuator` | One of each (`feed`, `capstan`, `takeup`), plus calibration. Enforces `VACTUAL == 0` before coordinated motion. Turns "takeup, 30 RPM" into pulses plus the current and microstep configuration behind them | Control policy |

### The port

The library's only output is bytes. A `tmc2209_port_t` supplies `tx`, `rx`,
optional `purge_rx`, optional `lock`/`unlock`, an optional `trace` hook, and
an `echoes` flag. Three backends follow: ESP-IDF wrapping `uart_read_bytes`
(`echoes = true`), the PC-side SIL link (`echoes = false`, full duplex), and
the unit-test mock.

There is no clock in this interface. Timeouts pass down as a millisecond count
and the port decides how to wait, which is what keeps the core free of ESP-IDF
and lets the unit tests run without sleeping. The consequence is that retries
are immediate, with no backoff. On a one-metre bus with three nodes that is
acceptable; the fix, if it ever is not, is a delay hook rather than a clock.

### Ownership and concurrency

There are **two separate transports**, which are easy to conflate:

```
PC ──USB Serial/JTAG──> [rpc task] ──queue──> [control task] ──UART1──> TMC bus ──> 3 drivers
                                                    │
                                                    └── stepgen (RMT) ──STEP/DIR──> drivers
```

The PC link is native USB, already the console. The TMC bus is a UART. There
is no contention on the wire, and UART2 stays free.

**One control task owns the TMC bus and all three devices.** RPC posts
requests into its queue rather than reaching the bus itself. The contention
being avoided is not the wire but the *transaction sequence*: an RPC task
answering on its own schedule would land between the control loop's poll and
the decision based on it.

Three actuators are not three independent controllers, because the film
physically couples them. Tension at the takeup is a function of what the
capstan does, and tension only exists *between* motors, so the loop has to see
all three. Step generation is hardware, so the loop only runs slow outer
control at 50-200 Hz, and §6's arithmetic gives roughly 300 Hz for all three
round-robin. The bus cadence and the control cadence are the same cadence, so
concurrency would buy no throughput and only add nondeterminism.

The library is therefore **not thread-safe by design**: one device, one owner.
The port's `lock`/`unlock` hooks stay NULL on target and exist for the PC-side
harness. The control task owning `stepgen` as well is what makes
`VACTUAL == 0` enforceable by construction rather than by defensive assertion.

---

## 5. Transport rules

**Echo.** TX and RX are joined at the carrier (§6), so every transmitted byte
comes back on RX. Exactly the echoed length is consumed before parsing a
reply. The echo is not discarded blindly: a mismatch between what went out and
what came back means something else drove the line during transmission, which
makes it the cheapest available bus-collision detector. Echo verification
therefore lives in the library where it is testable, and `echoes = false`
covers full-duplex backends.

**Read block.** Reads are sized exactly, for instance
`uart_read_bytes(port, buf, 12, timeout_ticks)`, which returns on either 12
bytes or a timeout. Nothing sleeps for a fixed interval.

**`SLAVECONF.senddelay` must be non-zero.** A shared bus needs the slave to
wait before replying so the master can release the line.

**Every write is verified.** A write datagram gets no reply, so `IFCNT` is the
only acknowledgement available.

Verifying one write means reading `IFCNT` and expecting it one higher than the
last observed value. Done per register, a ten-register configuration would
cost ten writes and ten reads. A batch is verified once instead: ten writes,
then one read expecting ten more, so eleven transactions rather than twenty.

The expected increase is a **range, not an exact number**, because a retried
write may have landed twice. An attempt whose echo came back corrupted can
still have reached the driver and been counted. Every register written is
idempotent, so rewriting one with the same value leaves the same state, and
anything between "each register landed once" and "every datagram sent was
counted" passes.

Because verification compares against a remembered baseline, a batch re-reads
`IFCNT` first whenever any `OWNED` slot is `UNKNOWN`. A passthrough write
advances the chip's counter without passing through the library, and verifying
against a baseline that cannot be vouched for would fail the very operation
meant to recover from it.

**Every read is CRC-checked**, and a mismatch retries rather than failing
immediately. A reply for the *wrong register* does not retry: it means a
second driver answered, which no number of attempts will fix. One wedged
driver must not stall the other two, so each transaction has a timeout,
bounded retries, and then faults the actuator.

**`GSTAT` is polled** through `poll_health()`. `DRIVER_RESET` means the driver
lost its configuration and every `OWNED` slot is now `UNKNOWN`. Because the
flag latches in silicon, recovery is two steps and not one: `write()` restores
the configuration, `clear_faults()` acknowledges the flag. Doing only the first
leaves the condition asserted forever. See §3.

---

## 6. Bus and wiring

**One shared single-wire UART for all three drivers**, addresses strapped
0/1/2 on MS1/MS2 per driver board.

The RJ45 cable carries the same eight conductors either way, so separate UARTs
buy no cable saving, and they would consume all three of the S3's UARTs with
none spare. Bandwidth is not close to a constraint: at 115200 a read
transaction is roughly 1.1 ms, so round-robin polling of three motors runs at
about 300 Hz, and the TMC2209 auto-detects baud from the sync byte, so 500k is
available if wanted. The accepted cost is that a wedged driver can hold the
line, which §5's timeout and retry rules contain.

Full pinout, straps, and board-level gotchas are in **`notes.md`**, under
*Hardware interface*. They are wiring facts rather than design decisions, and
this document is not where to look for a pinout.

---

## 7. Known defects: do not reproduce these

Items 1 to 6 were found in `cinescaner-drive`, the Python predecessor, while
deciding the above. They are recorded so the C implementation does not
reproduce them, and so the Python library can be fixed if it stays in service
as the PC-side diagnostic. Item 7 was found in the first C implementation.

1. **`scheme.py` and `registers.py` are byte-identical**, 654 lines each.
   Nothing imports `scheme`. Dead file.
2. **`push_base()` writes `FACTORY_CONF`**, which defaults to `fclktrim=0`.
   That overwrites the factory oscillator trim on every init, so every
   timing-derived quantity (`TSTEP`, `TPWMTHRS`, `TCOOLTHRS`, StealthChop
   frequency) drifts. This is why `FACTORY_CONF` is never written here.
3. **Reading write-only registers.** `pull_motion()` in full, plus
   `SLAVECONF` in `pull_base()`, plus the same registers in `probe.py`, whose
   report is therefore part fiction. See §2.
4. **Writes are never verified.** `read_ifcnt()` exists and nothing calls it.
5. **The read-timing hack.** See §5.
6. Minor: `self._vactual` is written and never read; `RegisterAddress` is
   imported unused in `tmc2209.py`; `pull_base`/`pull_motion` re-import
   module-level names locally; `__pycache__` is tracked in git.
7. **Adopting a driver wrote datasheet defaults over it.** The cache was
   seeded at construction with reset values, and `adopt()` ended by imposing
   the cache, so `init()` followed by `adopt()` wrote `mstep_reg_select = 0`
   and `pdn_disable = 0` to a fresh driver. That hands microstep resolution
   back to the address straps, which is the condition §0 exists to eliminate.
   The unit tests could not catch it: they asserted that the device matched
   the cache, which it did. The cache was wrong. Fixed by removing reset
   values from the table entirely and requiring `adopt()` to be given a
   configuration covering all ten `OWNED` registers.

---

## 8. Deferred, on purpose

- **Everything `TSTEP`.** `poll_step_period()` and the step-path verification
  in §0 both need a running step generator to exercise, so they are blocked on
  `stepgen` rather than merely postponed. Declared as placeholders so the
  shape is recorded.
- **The speed-dependent half of `poll_load()`.** Judging whether `SG_RESULT`
  falls inside the `TCOOLTHRS` window needs the current step rate, which
  arrives with `stepgen`, and per-motor calibration, which needs Phase 2
  hardware. The zero-`TCOOLTHRS` check ships now; the window check waits.
- **`PWMCONF` tuning.** Reset defaults plus autoscale until measurement says
  otherwise.
- **Per-actuator profiles.** Feed, capstan and takeup will not share current
  or StallGuard calibration, but the shape of that configuration is not worth
  guessing before Phase 2 hardware exists.
- **Any use for `MSCNT`.** The register is cheap to keep, but what it reports
  is electrical phase, not machine position, and no use for that has survived
  scrutiny. Revisit if a concrete need appears.
- **A typed configuration struct** replacing per-register writes. Considered
  and set aside: an ownership-based cache already gives the actuator layer
  most of what the struct would provide, and the batch write in §3 covers the
  rest.

### Strap cross-check

Designed, not built. `notes.md` warns that MS1/MS2 carry the bus address *and*
the power-on microstep resolution, and that a strap resistor that is not
populated changes both at once. `IOIN` reports the live state of those two
pins, and the library already knows which address it is talking to, so it can
compare them without any input from the caller:

```c
tmc2209_err_t tmc2209_verify_straps(tmc2209_t *dev);
```

It catches an unpopulated strap and, with three drivers on one wire, two
drivers sharing an address. It belongs to the `verify_` family because it
returns a verdict about something that should be true, and unlike a silicon
revision there is no policy involved: the correct answer is fixed by which
address the caller opened the device on.

Blocked only on confirming the address-to-`MS1`/`MS2` bit mapping against the
datasheet, which is not worth asserting from memory.

`ENN` is deliberately excluded. `notes.md` calls the pull-up on it the only
kill path that works when firmware is hung, so reading it back is worth doing,
but whether it *should* read high depends on whether the actuator has enabled
the motor. That is state this layer does not own, so `poll_pins()` reports the
pin and the caller judges it.

### Link statistics

Designed, not built. Recorded here because the decisions are settled and the
implementation is small enough that a later attempt would otherwise redo them.

**The problem.** A retry that succeeds is invisible. A bus that needs a second
attempt on every single transaction returns `TMC2209_OK` exactly like a
perfect one. Given §6's cable (one shared wire, a metre long, running near
24 V motor leads, with the weak DIR/EN pair described in `notes.md`), marginal
signal integrity is the most likely real fault, and it degrades across a reel
rather than failing cleanly. Nothing currently reports that.

**Shape.** A counter block per device, exported by a plain accessor:

```c
typedef struct {
    uint32_t datagrams;       /* attempts, including retries */
    uint32_t retries;         /* attempts beyond the first */
    uint32_t giveups;         /* transactions that exhausted retries */
    uint32_t crc_errors;      /* reply corrupted in flight */
    uint32_t echo_errors;     /* collision, or outbound corruption */
    uint32_t timeouts;        /* nothing answered */
    uint32_t io_errors;       /* the port itself failed */
    uint32_t wrong_register;  /* another driver answered: strap collision */
} tmc2209_link_stats_t;

void tmc2209_link_stats(const tmc2209_t *dev, tmc2209_link_stats_t *out);
```

The per-error split is the part that earns its keep: each counter names a
different physical cause. CRC means noise on the reply, echo means something
drove the line mid-transmission, timeout means a driver is wedged or
unpowered, and `wrong_register` means two drivers share an address.

**Per device, not per bus.** "Driver 2 retries ten times as often as the
others" identifies one cable and one connector; a bus-wide total only says
something is wrong somewhere. It is also the cheaper option, since
`tmc2209_bus_t` is `const` throughout including in the public
`tmc2209_bus_xfer()` signature, and counting into it would break that.

A side effect worth taking: `read_retrying()` and `write_retrying()` take the
bus and address separately today, but every caller already holds a `tmc2209_t`.
Passing the device instead removes a redundant parameter and supplies the place
to count.

**Datagram-oriented.** The datagram is the unit that can fail, so it is the
denominator. A ten-register batch contributes ten, not one. Any rate computed
downstream is per datagram.

**Zeroed at `init()`, never at `adopt()`,** which is the one decision worth
arguing. The counters have to be monotonic, because the consumer derives rates
by sampling twice and subtracting. `adopt()` can be called again to recover
from `DRIVER_RESET`, and if that reset the counters, a difference spanning the
recovery would go negative and wrap into a nonsense figure. Since `init()`
already zeroes the whole struct, this costs no code: it is a matter of
`adopt()` not touching them. Traffic during adoption then gets counted, which
is correct, because a driver that needed retries while being configured is
exactly what this is for.

**No window, and no verdict.** A lifetime average is the wrong statistic: a bad
thirty seconds at power-on would taint the figure for the rest of the reel.
Rather than pick a window size, the counters stay monotonic and the PC
differences them, the way OS network counters work. Wrapping is harmless under
unsigned subtraction, the same trick `confirm_writes()` uses on IFCNT. For the
same reason there is no `verify_channel_health()` in the library: "too many
retries" is a threshold, thresholds depend on cable length and installation,
and §3 puts policy above this layer. Such a verdict belongs in the actuator or
RPC layer and can be built entirely from these counters.

**Constraint this must not break.** §4 states that there is no clock in the
port interface, which is what keeps the core free of ESP-IDF and lets the unit
tests run without sleeping. Counters can therefore express failures *per
datagram* and never *per second*. The PC has a clock and converts. Do not add a
timestamp here to make a rate; that trades an architectural property for
arithmetic the consumer can already do.

**Known costs.** Counting must happen in exactly one place, or a future error
path added elsewhere will silently under-report; `read_retrying()` and
`write_retrying()` are that place and should stay so. The mock's fault
injectors are one-shot decrements, so testing a rate needs sustained patterned
injection, which is the bulk of the work. And the port's `trace` hook already
sees every byte, so a PC-side tool could derive the same numbers; counters win
for always-on use on target, but the overlap is real and only one of the two
should be treated as authoritative.
