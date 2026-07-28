# RPC

> **Design, ahead of code.** No RPC layer is built yet, so nothing here has been
> contradicted by an implementation. The `tmc2209` component it projects does
> exist: where this document and `tmc2209.h` disagree, the header is right.

`passthrough`, `raw` and `smart` are namespaces, differing by who assembles the
bytes: the PC, the firmware from a register you name, or the firmware from an
outcome you name. `sys` is the fourth, and answers about the firmware rather
than about a driver.

## How RPC Works

A register value is 32 bits on the wire between the ESP32 and the driver. The
question is what it should be on the wire between the PC and the ESP32, and the
tempting answer is a decoded object, because that is what a caller wants to
hold.

Decoding on the ESP32 means shipping field names and re-deriving the layouts
PC-side anyway, in a second language, from a datasheet. Two implementations of
one truth, and the second one drifts.

**The codecs are portable C.** `tmc2209_reg.c` and `tmc2209_frame.c` include
only `stdint.h` and their own header, with no ESP-IDF dependency, which is why
`test/unit/` already builds them on the host. Compile those two into a shared
object and the PC links the firmware's own codecs:

```
tmc2209_reg.c, tmc2209_frame.c
  ├── esp-idf build  ──> firmware
  └── host build     ──> libtmc2209.so ──> driver_link
```

So `driver_link` calls `tmc2209_gconf_decode()` and gets a real
`tmc2209_gconf_t`, calls `tmc2209_gconf_encode()` to build one, and assembles
passthrough datagrams with the library's own CRC. Nothing is duplicated because
nothing is reimplemented.

### The wire carries scalars, never structs

A struct is a memory layout, and a memory layout is padding, enum width and
`bool` size. Two compilers targeting xtensa and x86-64 are entitled to disagree
about all three, and adding a field to `tmc2209_drv_status_t` moves everything
after it while both ends still report the same version. Nothing in a handshake
catches that, because both ends are honest.

Nothing asks them to. Every decoded struct in `tmc2209_reg.h` is a view of one
`uint32_t`, so that `uint32_t` is what crosses, and the `.so` reconstitutes the
struct at the far end. The payload types are therefore exactly:

| On the wire | Becomes, PC side |
|---|---|
| `uint32` register value | `tmc2209_*_decode(value)` |
| `uint32` condition or slot bitmask | already the library's type |
| `int32`, `uint32` counters | themselves |
| `uint8`, `bool` | themselves |
| byte string | passthrough only, driver bytes verbatim |

`tmc2209_load_t` and `tmc2209_motion_t` are not register views, so they travel
as their scalar members and are reassembled by name. Two fields and four fields
respectively, which is cheaper than defending a layout.

This is why `raw.write` takes a `value` and not a `fields` object. The PC
already holds the encoder, so a caller sets `chopconf.toff` and calls
`tmc2209_chopconf_encode()` before the call goes out. The firmware receives a
number it does not have to interpret.

### Version skew

One `.so`, one firmware image, built from the same source tree, and no
guarantee the flashed board is the tree you are sitting in. `sys.version()`
answers it: `driver_link` asks once on connect and refuses a protocol version
it was not built against. A stale board is then a clean rejection at open time
rather than a decode that succeeds and lies.

### One port

The board exposes two USB-C connectors: a bridge chip wired to a UART,
silkscreened `COM`, and the S3's own USB Serial/JTAG controller, silkscreened
`USB`. RPC uses `USB`, and one cable is the whole story.

The native port is the only one that carries flashing, JTAG and RPC at once,
which is what makes it a single cable rather than a cable plus another for
debugging. It is also the faster path: full-speed USB at 12 Mbit/s straight into
the SoC, against roughly 90 KB/s across a bridge at 921600 baud with the chip's
latency timer, 1 ms and up to 16 ms on an FTDI part, sitting in every round
trip. Neither number is load-bearing today, since raw and passthrough are not
bound by the cadence budget, but streaming position during a move is a thing
smart might want and the bridge would have foreclosed.

What the native port costs is that it *is* the chip: its device node disappears
on every reset, and a firmware restart pulls the device out from under an open
file descriptor. `driver_link` reopens, and addresses the port through its
`/dev/serial/by-id` symlink so re-enumeration cannot rename it underneath. That
reconnect path is not extra work, because flashing over the same cable requires
it anyway.

One port also means `ESP_LOGI` cannot go to stdout, since raw text between
frames is exactly what a framer must not receive. `esp_log_set_vprintf()`
redirects the log stream into the framer, so a log becomes a frame type, and
`driver_link` sorts replies from logs as they arrive. The log then lands in the
orchestrator's own log file, on the orchestrator's clock, next to the PC-side
events it explains.

A serial port has one owner, which is the price. `driver_link` is what surfaces
the logs; there is no second terminal watching the same cable, and flashing
means closing the link.

One consequence for `driver_link`: DTR and RTS are what esptool drives to put
the chip into its bootloader, and opening a port asserts them by default. They
must be suppressed at open, or every connect reboots the board.

### Framing

A byte stream has no boundaries, so a frame is either delimited or
length-prefixed, and the two fail differently. A corrupted length is
unrecoverable: the receiver consumes N bytes of nothing and every frame after it
is misaligned, with no defined point of recovery.

**COBS** with a `0x00` delimiter, because it makes recovery defined rather than
likely. The encoding removes every zero byte from the payload, so a zero means
end-of-frame and can mean nothing else. A receiver that gets lost resynchronises
at the next zero byte, which is at most one frame away. Overhead is one byte per
254. SLIP buys the same property with escapes and a 2x worst case, so there is
no reason to prefer it.

A CRC16 inside the frame covers the other half: a frame that is well delimited
but corrupt is rejected instead of decoded.

### Payload

The scalars are laid out by **`rpc_wire.c`, compiled into the same `.so`**. It
is the codec argument applied a second time: rather than write a serialiser on
each side and keep them agreeing, write it once in portable C and let both ends
call it. Explicit little-endian, explicit widths, nothing memcpy'd, so this is a
layout with one implementation and not an ABI two compilers must agree on.

That is also why CBOR and protobuf are absent. They exist to negotiate structure
between parties that cannot share code, and these two can.

Three kinds of frame share the link, so the first byte says which:

| | Header | Then |
|---|---|---|
| `REQ` | `u8 type`, `u16 id`, `u8 ns`, `u8 method` | arguments |
| `REP` | `u8 type`, `u16 id`, `u8 status` | return values |
| `LOG` | `u8 type`, `u8 level`, `u32 uptime_ms` | tag and message, as text |

Every frame ends with `u16 crc`, and the whole thing is then COBS encoded. The
`id` echoes the request it answers, which is what lets `driver_link` pipeline if
it ever needs to and what keeps a late reply from being read as an early one.

### Request/response, plus logs

The ESP32 answers when asked, and otherwise emits only `LOG`. That one
unprompted frame carries no correlation, expects no acknowledgement, and obliges
nothing of the receiver, so it costs neither end any protocol state. A client
that does not care can discard it on the type byte alone.

Completion of an asynchronous `raw.move` is therefore discovered by polling
`raw.motion`, which is what that method is for. If smart later needs a lower
latency answer than polling gives, an event frame is an addition to make then,
against a measurement rather than in advance.

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

**Raw is a projection of the `tmc2209` component's public API onto RPC.** One
method, one library function, same parameters, same semantics, same error code.
That is the boundary rule: if it is a `tmc2209_*` call it belongs here, and
nothing here decides anything the library has not already decided. The table
below is therefore generated by reading `tmc2209.h`, and any disagreement with
that header is a bug in the table.

Error names are the library's `TMC2209_ERR_*` names with the prefix dropped.
Raw does not invent an error vocabulary, because it does not invent errors.
`ARG` covers a name the firmware cannot resolve, since an unknown device or
register never reaches the library.

So the cache is visible at this tier, not hidden behind it. Raw is raw with
respect to the ESP32, and the cache is part of what the ESP32 is. Reading it and
reading the silicon are two different questions, which is why they are two
methods.

Every method takes `dev`, a device name, as its first parameter. `REFUSED` is
the one status raw adds on its own: a policy gate, on the same conditions as
passthrough, checked before the library is called at all.

### Registers

<table>
<tr><th>Method</th><th>Does</th><th>Parameters</th><th>Returns</th><th>Status</th></tr>
<tr>
  <td rowspan="2"><code>raw.read</code></td>
  <td rowspan="2">Reads the cached value: what this firmware believes the driver holds. No bus traffic, so no transport can fail.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>reg</code>: register name.</td>
  <td rowspan="2"><code>{status, value}</code>. The <code>.so</code> decodes it, for the registers that have a codec.</td>
  <td><b>OK</b><br>The slot is valid.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>ARG</code>: unknown device or register.<br><code>ACCESS</code>: volatile register. The driver writes it, so no cached copy can be true.<br><code>INVALID_SLOT</code>: never written, or voided by a driver reset or a passthrough write.</td>
</tr>
<tr>
  <td rowspan="2"><code>raw.poll</code></td>
  <td rowspan="2">Reads the register off the driver, over the wire, uninterpreted. Does not consult or update the cache.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>reg</code>: register name.</td>
  <td rowspan="2"><code>{status, value}</code>.</td>
  <td><b>OK</b><br>Reply validated against sync, master address, register and CRC.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>ARG</code>: unknown device or register.<br><code>ACCESS</code>: write-only driver-side, so there is nothing to read.<br><code>NO_BACKEND</code>: no bus attached.<br><b>Transport</b>: <code>RX_TIMEOUT</code> driver silent, <code>TX_TIMEOUT</code>, <code>CRC</code>, <code>SYNC</code> wrong sync or master address, <code>REG</code> a register we did not ask about, <code>ECHO</code> something else drove the line, <code>IO</code> the UART peripheral failed.<br><code>REFUSED</code>: unsafe operation (e.g. film is moving).</td>
</tr>
<tr>
  <td rowspan="2"><code>raw.write</code></td>
  <td rowspan="2">Writes a batch of owned registers and confirms the whole batch with one <code>IFCNT</code> read. Updates the cache on success. The array is the unit of work, so ten registers cost eleven transactions rather than twenty.</td>
  <td rowspan="2"><code>dev</code>: device name.<br><code>ops</code>: 1..n entries, each a <code>reg</code> and a <code>value</code>, encoded PC-side.</td>
  <td rowspan="2"><code>{status, failed_at}</code>. <code>failed_at</code> is diagnostic only; see the note on failure below.</td>
  <td><b>OK</b><br><code>IFCNT</code> accounted for every datagram sent. A batch whose values already match valid slots sends nothing and still returns <b>OK</b>.</td>
</tr>
<tr>
  <td><b>ERR</b>, carries nothing<br><code>ARG</code>: unknown device or register, or an empty batch.<br><code>ACCESS</code>: a register that is not owned.<br><code>NO_BACKEND</code>: no bus attached.<br><code>NO_ACK</code>: <code>IFCNT</code> did not account for the writes issued.<br><b>Transport</b>: as above, on a datagram or on the confirmation.<br><code>REFUSED</code>: unsafe operation.</td>
</tr>
</table>

### Conditions and verdicts

Every method here puts a datagram on the wire, so every one of them can return
the transport set, `NO_BACKEND` and `REFUSED`. Only the errors peculiar to a
method are listed.

| Method | Does | Parameters | Returns | Also errors |
|---|---|---|---|---|
| `raw.poll_health` | Reads `GSTAT` and `DRV_STATUS` as one condition set. Observational: latched conditions stay asserted until acknowledged. `DRIVER_RESET` invalidates every owned slot. | none | `{status, conditions}` bitmask | |
| `raw.clear_faults` | Acknowledges latched conditions so they stop being reported. Pass back what `poll_health` gave. Live conditions in the set are ignored. | `conditions` | `{status}` | `NO_ACK` |
| `raw.poll_load` | StallGuard load estimate with whether it can be believed. `usable` is false outside the `TCOOLTHRS` window, and a number without it invites a control loop to act on noise. | none | `{status, sg_result, usable}` | |
| `raw.poll_pins` | Live input pin states, decoded, as the driver sees them. | none | `{status, value}`, `IOIN` | |
| `raw.poll_version` | Revision byte of whatever answers at this address. Reported, not judged. | none | `{status, version}` | |
| `raw.verify_config` | Compares cache against driver for the two owned registers that read back, `GCONF` and `CHOPCONF`. | none | `{status, mismatched}` bitmask | `MISMATCH` |

### Runtime writes

| Method | Does | Parameters | Returns | Also errors |
|---|---|---|---|---|
| `raw.set_velocity` | Sets `VACTUAL`. Non-zero takes the driver off its STEP pin silently, so it must return to zero before any move. | `v`: signed 24-bit | `{status}` | as `raw.write`, one register |
| `raw.set_current` | Sets run current, hold current, and the ramp between them. A runtime write, not configuration: reel torque has to track radius. | `ihold`, `irun`, `iholddelay` | `{status}` | as `raw.write`, one register |

`set_velocity` belongs here rather than in smart because it is a register write
the library wraps. Smart moves film with STEP/DIR over stepgen and never touches
`VACTUAL`, which is a test path and an assert.

### Bring-up and cache

| Method | Does | Parameters | Returns | Also errors |
|---|---|---|---|---|
| `raw.bringup` | Probes the driver, seeds the `IFCNT` baseline, hands back `GSTAT` as found, clears it, reads the constants off this part, writes the configuration. Returns with the driver holding it and standing still. | `config`: one entry per owned register, all of them | `{status, at_bringup}` | `ACCESS`, `NO_ACK` |
| `raw.all_owned_valid` | Whether every owned slot is valid. No bus traffic. | none | `{status, valid}` | `ARG` only |
| `raw.invalidate_owned` | Voids every owned slot. Constant slots survive, since a brownout does not change the factory trim. | none | `{status}` | `ARG` only |

### Lines

The caller never names a GPIO number. Naming a device and a line means the board
table is the only thing that knows the pin, so an unwired line is a clean
rejection instead of an arbitrary pin toggling.

Lines are **electrical**, matching the library: `line_write(STEP, true)` drives
high, and nothing here interprets what high means. The one signal whose polarity
is a property of the part rather than of the board is `ENN`, and `raw.enable`
exists precisely so that the caller says what it wants instead of what level
achieves it.

`STEP` is writable only on a device with no stepgen attached. A peripheral bound
to a pin and a GPIO write to the same pin are two owners, not two views, so
`raw.move` is the way to emit pulses on a configured device.

| Method | Does | Parameters | Returns | Errors |
|---|---|---|---|---|
| `raw.line_read` | Present level on a line, ESP32 side. For an output, the level being driven. | `line`: `ENN`, `DIR`, `STEP`, `DIAG` | `{status, level}` | `ARG`, `NO_BACKEND`, `UNWIRED`, `IO` |
| `raw.line_write` | Drives a line. Immediate, no sequencing, no preconditions checked. | `line`, `level` | `{status}` | above, plus `ACCESS` on `DIAG` or on `STEP` with a stepgen attached, plus `REFUSED` |
| `raw.enable` | Enables or disables the power stage, polarity applied. Nothing is checked: a driver with `CHOPCONF.toff` of zero enables and still holds no current. | `on` | `{status}` | as `line_write` for `ENN` |
| `raw.is_enabled` | The ESP32's view of the power stage. `IOIN.enn` is the driver's, via `raw.poll_pins`. | none | `{status, on}` | as `line_read` for `ENN` |

### Motion

Same projection rule, over the stepgen half of the library. This is the bench
path for the tension experiments in Smart below, and none of it is coordinated:
one device, one move.

| Method | Does | Parameters | Returns | Errors |
|---|---|---|---|---|
| `raw.move` | Starts a move and returns as soon as the pulses are on their way. The only asynchronous method in raw. Sets `DIR`, then starts the train, in that order, and holds `DIR` until the last pulse is out. | `dir` (the level), `shaft` (the `GCONF.shaft` the move was planned around, written to the driver if it holds the other), `pulses` (0 runs until halted), `pullin_pps`, `cruise_pps`, `accel_pps_s` | `{status}` | `ARG`, `RATE`, `NO_BACKEND`, `UNWIRED`, `BUSY`, `UNREAD` (the last run's count was never collected), `INVALID_SLOT` (`GCONF` uncached), `ACCESS` (`VACTUAL` non-zero), `IO`, `REFUSED`, plus anything the `GCONF` write can return |
| `raw.retarget` | Changes the cruise rate of a run in flight, at the run's original accel. What an unbounded run is for. | `cruise_pps` | `{status}` | `ARG`, `RATE`, `NO_BACKEND`, `IDLE`, `IO` |
| `raw.halt` | Ends the run. Not an emergency stop: `immediate` still finishes the pulse in progress. Halting an idle driver succeeds and does nothing. | `immediate` | `{status}` | `ARG`, `NO_BACKEND`, `IO` |
| `raw.motion` | The run's pulse count, rate and state. Collecting it once the run is over is what clears the way for the next `raw.move`; calling it mid-run reports progress and clears nothing. There is no odometer: a position is a sum of run counts, and what those pulses meant is the PC's to decide. | none | `{status, emitted, rate_pps, running}` | `ARG`, `NO_BACKEND`, `IO` |

Notes:

- No `WARN` tier, by construction. Raw validates the reply before yielding a
  value, so a result either carries a trustworthy value or carries nothing.
- `value` is what crosses and is always authoritative; a decoded struct is a
  view the PC builds from it. Reserved and undocumented bits survive in `value`
  even when no field names them, which is the case raw exists for.
- The firmware interprets nothing it does not need to. Encoding and decoding
  happen at the ends, PC-side through the shared `.so`, driver-side in silicon.
- `raw.read` against `raw.poll` is the diagnostic worth having. One
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
- Which GPIO a line is, and whether it is wired at all, comes from the board
  table. The library carries the line abstraction but not the pin numbers, so
  `UNWIRED` is answered ESP32-side either way.
- `raw.move` does not check that the driver is enabled or that `CHOPCONF.toff`
  is non-zero. On a disabled driver it returns `OK`, emits its pulses, counts
  them, and moves nothing. Expected rather than a defect, and the reason the
  odometer is pulses emitted and not film moved.
- `raw.line_read(dev, DIAG)` and `raw.poll(dev, IOIN)` observe the same
  pins from opposite ends of the trace. Disagreement between them is evidence
  neither reading can produce alone.
- Not a production path. The orchestrator uses `smart` only; raw and passthrough
  serve the bench and the Integrity suite. Neither is bound by the per-frame
  cadence budget, so neither should ever be optimised for it.

## Sys Behaviour

> Status: placeholder.

The one namespace whose questions are not about a driver. Before a link can
carry `raw` at all, the PC has to know it is talking to this firmware, at a
protocol version it understands, on a board whose device names mean what it
assumes. Nothing in the other three namespaces can answer that, since all of
them presuppose it.

`sys.version` is the one method already committed to, because the shared `.so`
depends on it: it reports the RPC protocol version and the firmware build, and
`driver_link` calls it on connect before anything else. It is also the only
method that must answer on a link whose version has not been agreed yet, so its
own reply shape can never change.

Further candidates: reset reason, the board's device and line table, uptime and
heap. Each is a fact about the ESP32 rather than a `tmc2209_*` call, which is
exactly what keeps it out of `raw`.

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
