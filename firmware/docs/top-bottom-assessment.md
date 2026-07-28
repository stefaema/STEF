# RPC

> **[OUTDATED, IF CODE DIFFERS IS BECAUSE THIS IS WRONG, NOT THE CODE]**

`passthrough`, `raw` and `smart` are namespaces, differing by who assembles the
bytes: the PC, the firmware from a register you name, or the firmware from an
outcome you name.

## Passthrough Behaviour

<table>
<tr><th>Method</th><th>Does</th><th>Parameters</th><th>Returns</th><th>Status</th></tr>
<tr>
  <td rowspan="3"><code>passthrough.send</code></td>
  <td rowspan="3">Puts the datagram on the wire unaltered and hands back what the driver answered, undecoded.</td>
  <td rowspan="3"><code>datagram</code>: 1..32 bytes, driver address in byte 1.<br><code>reply_len</code>: exact bytes to wait for, 0 for a write.</td>
  <td rowspan="3"><code>{status, bytes}</code>, always this shape.</td>
  <td><b>OK</b><br>Exactly <code>reply_len</code> bytes arrived.</td>
</tr>
<tr>
  <td><b>WARN</b>, carries bytes<br><code>REPLY_LEN_MISMATCH</code>: fewer bytes than asked for, including none.<br><code>ECHO_MISMATCH</code>: our own bytes came back altered, something else drove the line.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>REFUSED</code>: unsafe operation (e.g. film is moving).<br><code>BAD_ARGS</code>: datagram empty or over 32 bytes, or <code>reply_len</code> over the buffer.<br><code>IO</code>: the UART peripheral failed.</td>
</tr>
</table>

Notes:

- This behaviour is intended to be even more raw than Raw namespace, so bad CRC, etc is not diagnosed here.
- The severity tier tells a client whether the response still carries data.
- `REPLY_LEN_MISMATCH` is a warning because silence may not mean an error (e.g. On purpose Bad CRC check)
- A passthrough write invalidates the cache. Reads are exempt if unambiguously a
  well-formed 4-byte read request.
- Passthrough writes are unverified. No `IFCNT` check ESP32 side.
- Backed by `tmc2209_bus_send()`, which reports the byte count through
  `rx_got`.

## Raw Behaviour

> Status: designed, not built.

Passthrough asks a lot of its caller.

Raw is the same access with some of the protocol lifted off. You name a device and a
register, the firmware assembles the datagram, and a CRC that does not validate
comes back as an error instead of as data. **Passthrough reports what happened;
raw reports whether it worked.** That single difference is what removes the
`WARN` tier here.

**Raw is a projection of the `tmc2209` component's API onto RPC.** One method,
one library function, same semantics. That is the boundary rule: if it is a
`tmc2209_*` call it belongs here, and nothing here decides anything the library
has not already decided.

So the cache is visible at this tier, not hidden behind it. Raw is raw with
respect to the ESP32, and the cache is part of what the ESP32 is. Reading it and
reading the silicon are two different questions, which is why they are two
methods.

### Registers

<table>
<tr><th>Method</th><th>Does</th><th>Parameters</th><th>Returns</th><th>Status</th></tr>
<tr>
  <td rowspan="2"><code>raw.read</code></td>
  <td rowspan="2">Reads the cached value: what this firmware believes the driver holds. No bus traffic, so no transport can fail.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>reg</code>: register name.</td>
  <td rowspan="2"><code>{status, value, fields}</code>. <code>value</code> always. <code>fields</code> only for the registers that have a codec.</td>
  <td><b>OK</b><br>The slot is valid.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>BAD_ARGS</code>: unknown device or register.<br><code>ACCESS</code>: volatile register. The driver writes it, so no cached copy can be true.<br><code>INVALID_SLOT</code>: never written, or voided by a driver reset or a passthrough write.</td>
</tr>
<tr>
  <td rowspan="2"><code>raw.poll_register</code></td>
  <td rowspan="2">Reads the register off the driver, over the wire, uninterpreted. Does not consult or update the cache.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>reg</code>: register name.</td>
  <td rowspan="2"><code>{status, value, fields}</code>.</td>
  <td><b>OK</b><br>Reply validated against sync, master address, register and CRC.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>BAD_ARGS</code>: unknown device or register.<br><code>ACCESS</code>: write-only driver-side, so there is nothing to read.<br><code>NO_REPLY</code>: driver silent after the bus retry policy.<br><code>BAD_CRC</code>: reply arrived corrupt.<br><code>BAD_REPLY</code>: wrong sync, master address, or a register we did not ask about.<br><code>ECHO_MISMATCH</code>: something else drove the line.<br><code>IO</code>: the UART peripheral failed.<br><code>REFUSED</code>: unsafe operation (e.g. film is moving).</td>
</tr>
<tr>
  <td rowspan="2"><code>raw.write</code></td>
  <td rowspan="2">Writes a batch of owned registers and confirms the whole batch with one <code>IFCNT</code> read. Updates the cache on success. The array is the unit of work, so ten registers cost eleven transactions rather than twenty.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>ops</code>: 1..n entries, each a <code>reg</code> plus exactly one of <code>value</code> or <code>fields</code>.</td>
  <td rowspan="2"><code>{status, failed_at}</code>. <code>failed_at</code> is diagnostic only; see the note on failure below.</td>
  <td><b>OK</b><br><code>IFCNT</code> accounted for every datagram sent. A batch whose values already match valid slots sends nothing and still returns <b>OK</b>.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>BAD_ARGS</code>: unknown device or register, empty batch, both or neither of <code>value</code> and <code>fields</code>, or a field out of range.<br><code>ACCESS</code>: a register that is not owned.<br><code>NO_ACK</code>: <code>IFCNT</code> did not account for the writes issued.<br><code>NO_REPLY</code>, <code>BAD_CRC</code>, <code>BAD_REPLY</code>, <code>ECHO_MISMATCH</code>, <code>IO</code>: as above, on a datagram or on the confirmation.<br><code>REFUSED</code>: unsafe operation.</td>
</tr>
</table>

### The rest of the library

By the same rule these are raw too, and are tabled alongside the above:
`poll_health`, `poll_load`, `poll_pins`, `poll_version`, `clear_faults`,
`verify_config`, `set_velocity`, `set_current`, `bringup`, `invalidate_owned`,
`all_owned_valid`.

`set_velocity` belongs here rather than in smart because it is a register write
the library wraps. Smart moves film with STEP/DIR over stepgen and never touches
`VACTUAL`, which is a test path and an assert.

### Pins

Pin roles are **positive logic**. `set` means the named condition is true, and
the board table holds the physical polarity. `ENN` on the TMC2209 is active-low
and is exposed here as the role `EN`, so `pin_set(capstan, EN)` enables the
driver and drives the pin low. This is a property of the namespace and not a
rename of one signal: any active-low signal wired later is converted the same
way, in the same table.

The caller never names a GPIO number. Naming a device and a role means the
board table is the only thing that knows the pin, so an unwired role is a clean
rejection instead of an arbitrary pin toggling.

<table>
<tr><th>Method</th><th>Does</th><th>Parameters</th><th>Returns</th><th>Status</th></tr>
<tr>
  <td rowspan="2"><code>raw.pin_read</code></td>
  <td rowspan="2">Reads a pin's present state, ESP32 side. For an output this is the level being driven.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>role</code>: <code>EN</code>, <code>DIR</code>, <code>STEP</code>, <code>DIAG</code>.</td>
  <td rowspan="2"><code>{status, state, level}</code>. <code>state</code> is logical, <code>level</code> is electrical.</td>
  <td><b>OK</b></td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>BAD_ARGS</code>: unknown device or role.<br><code>UNWIRED</code>: the role is not connected on this board.</td>
</tr>
<tr>
  <td rowspan="2"><code>raw.pin_set</code><br><code>raw.pin_clear</code></td>
  <td rowspan="2">Drives a pin to make the named condition true or false. Immediate, no sequencing, no preconditions checked.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>role</code>: an output role.</td>
  <td rowspan="2"><code>{status, state, level}</code>, as read back after the write.</td>
  <td><b>OK</b></td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>BAD_ARGS</code>: unknown device or role.<br><code>UNWIRED</code>: the role is not connected on this board.<br><code>ACCESS</code>: the role is an input and cannot be driven (e.g. <code>DIAG</code>).<br><code>REFUSED</code>: unsafe operation.</td>
</tr>
<tr>
  <td rowspan="2"><code>raw.pin_pulse</code></td>
  <td rowspan="2">Emits exactly one pulse. Width is chosen firmware-side from the driver's minimum, so no RPC round-trip timing is involved and there is nothing to parameterise.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>role</code>: a pulsable output role, in practice <code>STEP</code>.</td>
  <td rowspan="2"><code>{status}</code>.</td>
  <td><b>OK</b><br>The pulse was emitted. Not that the motor moved.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>BAD_ARGS</code>: unknown device or role.<br><code>UNWIRED</code>: the role is not connected on this board.<br><code>ACCESS</code>: the role is not pulsable.<br><code>REFUSED</code>: unsafe operation.</td>
</tr>
</table>

Notes:

- No `WARN` tier, by construction. Raw validates the reply before yielding a
  value, so a result either carries a trustworthy value or carries nothing.
- `value` is always present and always authoritative; `fields` is a view of it.
  Reserved and undocumented bits survive in `value` even when no field names
  them, which is the case raw exists for.
- Field layouts are never duplicated PC-side. The codecs in `tmc2209_reg.h` run
  on the ESP32 and the decoded names go out on the wire, so the tool renders
  whatever keys arrive.
- `raw.read` against `raw.poll_register` is the diagnostic worth having. One
  reports what the ESP32 believes, the other what the silicon answers, and a
  disagreement between them is a bug that neither call can expose alone.
  `verify_config` is that comparison formalised, for the two owned registers
  the driver will answer for.
- Raw writes **maintain** the cache, because they are the library's own writes.
  Passthrough writes invalidate it, because they are not. That is the cache
  difference between the two tiers, and it follows from who assembled the bytes.
- Batch semantics come from `tmc2209_write()` unchanged. Applied in order, a
  register named twice takes its last value, an op already matching a valid slot
  is dropped, and **any failure invalidates every slot in the batch**, including
  ops transmitted before the failure. Nothing is confirmed until the closing
  `IFCNT` read, so `failed_at` says where the library gave up and not where the
  state boundary is. Recovery is to re-send the batch.
- `REFUSED` is the one piece of policy raw carries, on the same conditions as
  passthrough. It would be incoherent for a higher tier to permit what a lower
  one refuses: abstraction level is not consent.
- Pins are the one part of raw that is not projected from the library, which has
  no GPIO knowledge at all. They come from the board table instead. Same shape,
  one device and one primitive operation, different source of truth.
- `pin_pulse` does not set `DIR` for you and does not check that the driver is
  enabled or that `CHOPCONF.toff` is non-zero. Calling it on a disabled driver
  returns `OK` and moves nothing, which is expected rather than a defect.
- `raw.pin_read(dev, DIAG)` and `raw.poll_register(dev, IOIN)` observe the same
  pins from opposite ends of the trace. Disagreement between them is evidence
  neither reading can produce alone.
- Not a production path. The orchestrator uses `smart` only; raw and passthrough
  serve the bench and the Integrity suite. Neither is bound by the per-frame
  cadence budget, so neither should ever be optimised for it.

## Smart Behaviour

Smart cannot be designed yet, because two of its answers are measurements and
not choices. Everything below is a candidate to be tested at F3, plus the
constraints that already rule some candidates out on paper.

The two questions:

1. How is the film kept tense enough?
2. How does a move converge on a frame the vision algorithm accepts, fast
   enough to beat the 2 s/frame manual baseline (R11)?

---

## 1. Tension

Feed reel, capstan, takeup reel. The capstan meters film; the reels manage what
is on either side of it. Reel radius changes as film winds, so nothing about
this is constant across a scan.

### The constraint that ranks the candidates

**A stepper holding position is not a torque source.** With `IHOLD` applied and
no stepping, the motor behaves as a spring around its present microstep, not as
a constant back-tension. Restoring torque grows with angular error, peaks near
one full step of lag, then collapses as the rotor slips to the next detent.

A reel being overhauled by film therefore delivers a **sawtooth**, not steady
tension: build, slip, build, slip, 200 times per revolution on a 1.8° motor.
Any scheme that leans on hold current to set tension inherits that ripple.

### The mechanical question underneath

**Are the tension rollers sprung dancers or fixed idlers?** This decides more
than any control choice.

Sprung, the spring sets film tension and the reel motors only have to keep the
arm inside its travel. The sawtooth is absorbed by the compliance and radius
changes stop mattering moment to moment. This is what production transports do.

Fixed, reel torque becomes film tension with nothing in between, every step slip
is felt at the gate, and the cogging fight is permanent.

Worth settling before running any experiment below, because with a dancer the
control problem is close to trivial, and without one the experiment may be
measuring an artifact that a spring designs away.

### Candidate schemes

| Scheme | Mechanism | Assessment |
|---|---|---|
| **A. Differential hold** | Feed applies holding torque against unwind. Takeup applies winding torque, exceeding feed by a margin. The capstan is the decisive element that grounds motion. | Closest to production practice. Depends on the sawtooth being absorbed somewhere, so it is the scheme a dancer rescues. StallGuard is unavailable on a reel that is only holding. |
| **B. Opposed drive** | Feed driven against the direction of travel, takeup driven with it, both actively turning. Current sets torque on each. | Both reels turn, so StallGuard is usable for live tension sensing. Costs continuous power and motor heat, which R02 cares about. Current balance depends on reel radius, so it needs the radius estimate below. |
| **C. Phased takeup** | Everything holds, the capstan advances, then a separate phase stops the capstan and lets the takeup tighten. | Rejected. Slack accumulates on the takeup side during the advance, while the feed side carries the sawtooth anyway. Adds a phase per frame against a cadence target, and repeated tighten and loosen cycles work brittle material harder than steady light tension. |

### Two constraints on all of them

**Constant current is not constant tension.** Tension = torque / radius. A 400 ft
16 mm reel on a 2 in core swings radius by 2 to 3x between empty and full, so a
fixed `IRUN` gives tension that drifts by that factor across a scan, in opposite
directions for feed and takeup. Something must track radius.

Radius is available with no added sensor. The capstan meters a known length, so
watching how far a reel turned to absorb it gives `r = ΔL / Δθ`, updated
continuously. Same trick as the pixel calibration below, on different quantities.

**StallGuard cannot read a stationary reel.** `SG_RESULT` is only meaningful
inside the `TCOOLTHRS` speed window, which is why `tmc2209_poll_load()` reports
`usable` next to the number. A holding reel produces no signal at all. This is
what makes StallGuard available in scheme B and absent during the hold in
scheme A.

---

## 2. Convergence

A move must land the next frame inside the vision algorithm's tolerance, in as
few vision passes as possible.

### Rejected: fine-grained closed loop

Step, check vision, step, check vision. Each vision pass costs tens of
milliseconds and a frame is hundreds of microsteps away, so the round trips
alone blow the cadence budget. Vision is the expensive operation and the
algorithm has to be miserly with it.

### The two unknowns behave differently

Separating them removes most of the difficulty.

**k, pixels per microstep.** The capstan has a fixed radius, unlike the reels,
so k is genuinely constant. Calibrate once and trust it.

**N, microsteps per frame.** Not constant. Frame pitch drifts with shrinkage,
which is exactly the failure that makes open-loop advance unusable and is
already argued in the report at §2.2.

### Steady state

Keep a **running estimate of N**, updated every frame from where vision actually
found the frame:

1. Advance `N_est - M` in one move.
2. One vision pass measures the residual.
3. Correct forward.
4. Feed the correction back into `N_est`.

The correction distance is itself the measurement of the error in `N_est`, so
the loop calibrates against shrinkage drift as it scans rather than assuming a
pitch that was true at the start of the reel.

### Bootstrap

A new reel starts with N unknown, and that is where a coarse ladder earns its
place: advance a fraction, look, refine, until N is bracketed well enough to
enter steady state. Once per reel, not once per frame.

### Approach from one direction only

Do not reverse the capstan to trim an overshoot. Backlash plus film stretch
makes a reversal non-repeatable, so the position reached after backing up is not
the position the model believes.

Always undershoot, always approach forward. Size `M` from the observed spread of
`N_est`, roughly 3σ, so overshoot is rare. When it happens anyway, back up by
more than the backlash and re-approach forward rather than nudging backward into
place.

---

## 3. Where the strategies live

**Not as a parameter flag on the smart API.**

The three tension schemes are an experiment, and an experiment does not need
smart methods. Each of them needs only per-device current and velocity, which
`raw` already exposes because raw is a faithful projection of the `tmc2209`
component. All three can be driven from Python over the existing RPC, at F3,
before any of smart exists.

This is what raw is for, and the roadmap already sequences it that way: F3 is
built first, and `actuator` plus smart come after.

Smart then implements the scheme that won. What stays configurable is the
**numbers**, currents, over-speed fraction, `M`, the radius model, not the
**strategy**. A shipped API with a strategy flag is usually a decision that was
never made, and it commits the firmware to maintaining designs nobody believes
in.

The honest exception: if two schemes serve genuinely different modes, gentle
frame-by-frame scanning against fast rewind, those are two named methods and not
one flag.

### `calibrate`

Belongs in smart, and returns k, N₀ and the initial radius estimates to the PC
rather than persisting them in NVS. Calibration then travels with the scan
session and gets recorded next to the material it was measured on, instead of
sitting invisibly in firmware across reboots.
