# Transport

The PC-side of the film transport. Working design notes, not final prose.

## What it is

Transport is a Python package with two consumers and two layers.

The consumers are the orchestrator, which drives the machine, and a diagnostic
front-end, which is a GUI today and could be a TUI. They get different APIs with
opposite stability guarantees.

The layers are the transport layer, bound to those consumers, and the link layer,
bound to RPC. The transport layer is where Python lives. The link layer owns the
serial port and the compiled C.

```
      orchestrator                    GUI
           │                           │
         scan                        bench
           │                           │
           └───────── transport layer ────┘
                          │
                     link layer
                          │
                 librpc.so  (ctypes)
                          │
                     USB / RPC
                          │
                       ESP32
```

## Two APIs

**scan.** Stable, small, implementation-free. FILM methods plus lifecycle:
`setup`, `teardown`. Any future transport offers this vocabulary or it is not a
transport. The orchestrator sees nothing else.

**bench.** A projection of what this transport currently is, so it changes when
the implementation changes. `sys`, `raw` and `passthrough`, the shadow, the check
registry, and the console. Reached only through the diagnostic front-end.

The names are the two situations, not two relationships to the code. `scan` is
what a subsystem does while the machine is doing its job, which is already the
firmware's word for it: `RPC_MODE_SCANNING` means a run owns the transport, even
though the transport scans nothing itself. `bench` is what you do to a subsystem
when it is out of service, which covers checks, bring-up and an operator setting
configuration.

They live in one package, split by folder. Both need the same link and the same
binding, so there is one of each.

## Both directions are a proxy

```
Operating:    orchestrator ──► transport   ──► ESP32 FILM
Diagnosing:   GUI          ──► orchestrator ──► transport bench
```

While operating, transport relays for the orchestrator. While diagnosing, the
orchestrator relays for the GUI, carrying payloads it does not interpret. It can
do that because the contracts are self-describing.

The orchestrator is on both paths, which is why it holds the mode.

## Modes

Operating, Diagnosing, Configuring. Exclusive. The orchestrator grants one.

This is PC-side policy. `sys.state` reports `mode` and is never set: the firmware
declines to hold a state that the PC would have to keep in sync across a link
that can drop. A check that needs the link to itself gets it because the
orchestrator stopped operating, not because the firmware was told.

## FILM is in the firmware

`RPC_NS_FILM` is reserved and empty. It will hold outcomes: advance this many
millimetres, hold tension.

The orchestrator names an outcome. The ESP32 owns the geometry, the microstep
resolution and the loop that produces it. Millimetres become pulses on the board
that emits the pulses.

So `scan` marshals arguments, seals a frame and waits. No control loop
crosses the serial link and no PC-side value participates in a motion decision.
That is what makes the shadow safe to be informative only: nothing on the PC bears
load.

## The C binding

The PC does not reimplement what the firmware implements. It compiles the same
sources and calls them.

`rpc_api.h` is the source of truth and stays hand-written. Its prose is
load-bearing: why `sys.version`'s strings are fixed width, why passthrough's
`outcome` is a value and not a status. Nothing generates that file.

What is generated is Python's view of it. libclang reads the headers the way the
compiler does, macros expanded and includes followed, and emits `fw_api.py`: a
`ctypes.Structure` per payload, an `IntEnum` per enum, an int per constant, and
`argtypes` with `restype` per function. Sizes, offsets and enum values are the
compiler's answer, so a method number cannot disagree across the link, and no
name is written twice. A field added to `rpc_api.h` reaches Python by
regenerating, and nowhere does anyone retype it.

CMake builds the sources into `librpc.so`, which ctypes loads. This follows the
convention already in the tree. `rpc/CMakeLists.txt` carries no `REQUIRES` and
depends on nothing, not even ESP-IDF, so its sources compile once as an IDF
component, once as a host static library under `rpc/test`, and a third time
here. Each consumer names the paths it wants. Transport owns this build.

### What crosses

| Compiled | `rpc/cobs.c`, `rpc/crc16.c`, `rpc/rpc_frame.c`, `shared/rpc_api/rpc_strerror.c`, `tmc2209/tmc2209_reg.c`, `tmc2209/tmc2209_frame.c`, `tmc2209/tmc2209_err.c` |
|---|---|
| Declared only | `rpc_proto.h`, `rpc_api.h`, and the enums and constants of `tmc2209_reg.h`, `tmc2209_lines.h`, `tmc2209_stepgen.h` |

`tmc2209_frame.c` is here because `passthrough` is defined as the PC assembling
the datagram, so the PC needs the datagram builder and its CRC8.

The header-only names matter as much as the sources. Every `reg`, `line` and
`conditions` field on the wire is a bare integer, and the enums are what make
them legible: `tmc2209_reg_t`, `tmc2209_line_t` with `TMC2209_LINE_BIT` and
`TMC2209_LINES_ALL` for decoding `rpc_dev_info_t.wired`, `tmc2209_condition_t`
with `TMC2209_CONDITIONS_LATCHED` and `TMC2209_CONDITIONS_FAULT`, the codec
enums, and `TMC2209_REG_COUNT` with `TMC2209_OWNED_COUNT` for the shadow's shape.

### What does not

`tmc2209.c`, `tmc2209_uart.c`, `tmc2209_lines.c` and `tmc2209_stepgen.c` exist to
drive backends through function pointers. The PC has no UART, no GPIO and no
pulse source.

`rpc_dispatch.c` is the server's method table.

`rpc_status.c` is the renumbering the firmware does on its way out, from
`TMC2209_ERR_*` to `RPC_*`. It runs before a reply is sealed and has nothing
left to do by the time one arrives.

## Two error vocabularies, and which one arrives

On the wire, only `RPC_*`. Every reply carries one in its header, and the
firmware has already renumbered the library's error into it.

In this process, `tmc2209_err_t`. It arrives from exactly one function:
`tmc2209_frame_parse_reply`, which the PC calls because passthrough is defined
as the PC assembling *and parsing* the datagram. So the library's vocabulary
does reach here, by a path that never touches the wire.

Both need naming for an operator, and both name themselves in C.
`tmc2209_strerror` already exists, and `rpc_strerror` now sits beside the values
it names, in `shared/rpc_api/rpc_strerror.c`.

It cannot borrow `rpc_status.c`'s trick of omitting `default` so that a new
value becomes a compile warning. That works there because it switches on
`tmc2209_err_t`, an enum. `rpc_status_t` is a typedef'd `uint8_t` on purpose:
`rpc_proto.h` argues the byte is shared out and an enum "would have to name all
of them in one place, which is the coupling this file exists without". A switch
over it gets no coverage warning, so the guarantee moves to a test that walks
every value below `RPC_STATUS_LAST`, plus the transport band, and fails on
"unknown".

Strings from C. Only the exception class is Python.

### What raises and what returns

`rpc_api.h` argues twice, in prose, that some non-OK results are values rather
than failures. Passthrough's `outcome`: a driver that stayed silent is an answer
here, and a failing status would have dispatch discard the bytes that prove it.
`verify_config`'s `mismatched`: a disagreement is a result, and the caller wants
to know which slots.

So the rule is read off the header rather than invented:

- **Frame status is not `RPC_OK`** the call did not happen. Raise.
- **An outcome inside a payload** the call happened, and this is what it found.
  Return it.

`tmc2209_err_t` from `parse_reply` lands on the second side without needing its
own rule, which is the sign the rule is cut in the right place.

### The exception classes

Generated from the status enum, like everything else: an `RpcError` base
carrying `.status` and the string from `rpc_strerror`, and one subclass per
value. A caller that only cares whether the call landed catches the base; a
check that means to tolerate `RPC_NO_ACK` and nothing else catches `RpcNoAck`.
Neither pays for the other.

Generating them is also what makes the coverage question moot. There is no
hand-written table to fall behind, and the test that every status has a class
reduces to asserting the generator ran, which `RPC_STATUS_LAST` already bounds.

### The generated module

`fw_api.py` is committed, not built on demand. libclang is a dev dependency and
nothing on the host needs it. A header change then arrives as a visible Python
diff in the same commit, rather than as behaviour that appears after someone
rebuilds. CI regenerates and asserts the diff is empty.

Four things the generator handles rather than discovers.

**Constants arrive two ways.** Both status bands are anonymous enums, one in
`rpc_api.h` and one in `rpc_proto.h`, which libclang reports directly. The
bounds are object-like macros: `RPC_MAX_OPS`, `RPC_STR_MAX`,
`RPC_STATUS_TRANSPORT_BASE`, the `TMC2209_*` masks. Macros need a preprocessing
record, and only ones expanding to an integer literal can be emitted, so
anything else has to fail the generator loudly rather than be skipped quietly.

**Flexible array members.** `rpc_sys_devices_ret.devs[]`,
`rpc_raw_write_args.ops[]` and `rpc_pt_send_args.tx[]` have no ctypes
equivalent. Each emits a fixed head, an element type, and the name of the field
carrying the count. The variable part is built per call.

**Sizes.** clang computes the layout and gcc compiles the library, which is a
seam worth naming. It is already closed: `RPC_WIRE_SIZE` pins every payload's
size inside the header, so the two compilers agree or one of them fails to
build. The generator emits each size as a literal regardless, and a test
compares it against `ctypes.sizeof`.

**Symbols.** ctypes resolves a symbol on first attribute access, so a wrong name
fails at runtime rather than at build time. The generator cannot invent one,
since every name comes from a header it parsed, and an import-time pass touches
all of them so the failure stays loud and early.

### What it looks like

```python
import ctypes
from transport import fw_api

args = fw_api.rpc_raw_move_args(idx=0, pulses=4000, cruise_pps=8000)

buf = fw_api.rpc_buf_t()
ctypes.memmove(fw_api.rpc_payload(buf), ctypes.byref(args), ctypes.sizeof(args))
n = fw_api.rpc_frame_seal_req(buf, rid, fw_api.RPC_NS_RAW, fw_api.RPC_RAW_MOVE,
                              ctypes.sizeof(args))
```

`rpc_frame_seal_req` is `rpc/rpc_frame.c` running in this process. The CRC is
`crc16.c`. One polynomial in the system.

Register decoding is the driver library's own codec:

```python
g = fw_api.tmc2209_gconf_decode(raw)
g.en_spreadcycle
```

### Why one module, and why that name

Every C symbol is already prefixed `rpc_` or `tmc2209_`, so the prefix is the
namespace and a second one would be redundant. Splitting into `rpc.py` and
`tmc2209.py` only pays off if the prefixes are stripped, and stripping them
costs the property the whole design exists for: `grep rpc_raw_move_args` finds
the header and the Python today, and after a rename it finds one. The generator
transcribes, it does not rename.

`fw_api` rather than `api` because transport now has two APIs of its own. This
one is the firmware's.

### Three tiers

```
fw_api.py + librpc.so   generated layouts, and the firmware's own functions.
link layer            frames, port, demux. Speaks ctypes.
scan and bench        namespaces, dataclasses, labels, validation. Speaks Python.
```

ctypes objects live and die in the link layer. `scan` and `bench` are where a
reply becomes a dataclass, which is the same boundary that serializes to JSON
and the same boundary that holds everything the compiler discarded.

The dataclasses are not generated. `fw_api.py` is a transcription of the headers
and stops there; what a reply should look like to a front-end is a decision made
where the labels and the intent already live.

## The link

`fw_api` is the vocabulary; the link is the only thing that speaks it. Nothing
above the link holds a ctypes object, and nothing below it holds a dataclass.

The serial port has one owner, reading continuously, splitting frames by type
and routing replies by request id.

Not a call that happens to also read. `RPC_FRAME_LOG` arrives unprompted,
carrying a level and an uptime, interleaved with replies to requests still
outstanding. Streaming check progress has the same shape. Everything else about
transport is request and response, and this is the one thing that is not, so the
link is built around it.

Log frames are consumed here and re-emitted as module-level log records. An
ESP32 log line is an implementation detail of this transport, and the
orchestrator's sink has to accept records from a capture subsystem that has
never heard of a frame.

## The shadow

What the PC believes each driver's registers hold. Display state. It is
refreshed on demand and marked stale rather than trusted.

It is named for the part it shadows, not for the idea, because it is bench and
bench is bound to what this transport actually drives. A second driver family
would get its own, beside this one.

Its policy is inherited, not invented. `tmc2209_reg_class_at()` comes across in
the binding and classifies every slot:

- **CONSTANT and OWNED** are read with `raw.read`, which maps to `tmc2209_read`
  and reads the ESP32's cache without touching the wire. This works for the
  eight write-only registers, where that cache is the only knowable truth short
  of the silicon.
- **VOLATILE** is refused by `raw.read` and is always polled. `poll_health`,
  `poll_load`, `poll_pins`, or `raw.poll`.

Believability comes from `raw.all_owned_valid`, and from `raw.verify_config` for
GCONF and CHOPCONF, the two owned registers that can be read back.

### What marks it stale

Only owned slots. Constant slots are what nothing writes, and volatile ones were
never in the shadow.

A FILM call invalidates all of them. Not because it writes registers, but
because the PC cannot know which: the orchestrator named an outcome and the
firmware chose what to touch. A move can write `GCONF.shaft`, a tension hold can
write `IHOLD_IRUN`, and neither is reported.

A bench write is precise. `raw.write`, `set_current`,
`set_velocity` and `bringup` are issued from here, so the affected slots are
known, and on success their values are known too, since the PC sent them and the
firmware confirmed them against IFCNT. On failure the whole batch goes, because
nothing in a batch is confirmed until that check.

Two events invalidate without any call at all, and both have wire answers.
`TMC2209_DRIVER_RESET` invalidates every owned slot, and
`sys.version.reset_reason` answers the reboot question in one byte. Refresh and
mark. Nothing is pushed and nothing needs to be.

Blanket invalidation is affordable because of the modes. Refresh costs thirteen
round trips per driver, and it is never paid during a scan: the diagnostic view
is open in Diagnosing, and FILM runs in Operating. One refresh on entry covers
it.

A snapshot is a value per register, its class, and whether the PC has reason to
believe it. It serializes to JSON for the front-end.

## Checks

Bound to this implementation in content, independent of it in envelope. The GUI
cannot know what "verify all three drivers answer at their strapped addresses"
means, and must still list it, run it, watch it and show a verdict.

Checks are declared next to the code they exercise and collect themselves at
import. A decorator carries the identity and the description and does the
collecting; the body is a generator that yields one step at a time, each
carrying what it did and how it went.

The verdict is the last thing yielded, not the return value. A consumer then
iterates to exhaustion and serializes what it gets, with no `StopIteration` to
catch and no second shape to handle. Matching on step kind belongs to that
consumer, not to the check.

`list_checks()` answers identity and description. `run_check(id)` answers the
stream.

They compose by granularity, which is what makes them usable during bring-up.
"Does RPC work" asks `sys.version` and stops. "Does the PC reach the TMC2209"
goes further. "Check everything" runs the set. An operator descends until
something fails.

Transport runs its own. It owns the link and knows the frame types, and a GUI
driving a check step by step would put protocol knowledge in the GUI. Checks
that need an operator in the loop are a step type, not an inversion of control.

Bring-up and checks touch without being the same thing. Some checks perform a
bring-up. Bring-up is not a check.

## Console

The GUI lets an operator command any subsystem directly and is not rewritten
when a subsystem changes. So it cannot know any subsystem's methods. It asks.

Transport describes its own surface: namespaces, methods, each method's
arguments with types and labels, each method's returns. The GUI renders a
structured form with Args and Rets tabs, a raw prompt underneath, and a live
preview of what will go out.

The description covers the **Python module surface**, not the RPC surface.
`setup` has no method number, and the front-end has no reason to learn that some
methods do.

For transport most of it is mechanical, since the binding already holds the
layouts. What the binding cannot supply is intent: that `idx` indexes the board
table `sys.devices` names, that `line` renders as a dropdown of
`tmc2209_line_t`, that `dir` is an electrical level and not a direction. Those
are authored per method.

## The contracts

Checks and console are one contract, read by the front-end and written by the
module. It carries a version; the versioning scheme is open.

It lives in `shared/`, by the tree's own logic. `shared/rpc_api` is the contract
between the ESP32 and the PC and sits outside both ends, because written twice
it drifts and the failure is silent. This is the same kind of thing one level
up, between a module and a front-end. Putting it in `shared/` also stops
transport, by being first, from deciding the shape for whoever comes second.

Console is optional. A module can declare checks and no console, and the
front-end has to render that. Checks are what every module has; a console is
what a module has when commanding it directly is meaningful, and that is not
knowable in advance.

## What stays hand-written

Method numbers and struct layouts are unforgeable once generated. One fact is
not: that `RPC_RAW_MOVE` takes `rpc_raw_move_args`. Nothing in the headers
states that pairing, so it is a Python table and has to be asserted rather than
trusted.

Alongside it, everything the compiler discarded. Field labels, ranges, and the
coherence rules that live in Doxygen: `accel_pps_s == 0` is only valid when
`cruise_pps == pullin_pps`, `pulses == 0` runs until halted.

## Known gaps

**No rate ceiling on the wire.** `tmc2209_stepgen_t.max_pps` is the fastest a
backend can emit and a rate above it is refused rather than clamped, which is
what `RPC_RATE` reports. `rpc_dev_info_t` carries `name`, `addr`, `wired`,
`has_uart` and `has_stepgen`, so the PC discovers the ceiling by being refused.

Left as it is, deliberately. The only callers that name a rate are `raw` and
`passthrough`, both of them bench, and on the bench a refusal is a complete
answer: you asked for something the hardware will not do and you were told so.
Publishing the ceiling would let a front-end grey out the impossible before it
is asked for, which is nicer and is not worth a payload change now. It becomes
a real question if anything in `scan` ever names a rate, and nothing does.

**No batched read.** `raw.write` batches up to `RPC_MAX_OPS`. `raw.read` is one
register per frame, so a full shadow refresh is thirteen round trips per driver
and `RPC_MAX_DEVICES` is 4. A live register view would want a batched read, and
that is a firmware change.

## Build

`transport/flake.nix` declares Python, gcc, cmake and libclang.

`ci/run.py:discover()` classifies a module by what is inside it, and a
`pyproject.toml` means pytest. Its cmake detection will not find this one:
`ctest_dirs` only collects `CMakeLists.txt` under a directory named `test` or
`tests`, and transport's sits at the module root because it builds the package's
library rather than a test. So it needs its own field, in the slot the cffi hook
used to hold.

The new part is sequencing. Transport is the first module that must compile
another module's C before its own tests can import anything, so `librpc.so` has
to exist before `pytest` runs, and it is not a ctest directory: nothing in it is
a test.

Regeneration is its own check: run the generator, and fail if `fw_api.py` moved.
That is what keeps the committed file honest without putting libclang in the
path of an ordinary test run.

`firmware/scripts/rpc_console.py` is deleted. It was a bench script, it carries
its own C parser, its own CRC16 and its own COBS, and everything it did is
covered here.

## Layout

The module directory is the package. No `src/`, no repeated name.

```
transport/
  CMakeLists.txt    librpc.so, from rpc/, shared/ and tmc2209/ sources
  fw_api.py         generated: layouts, enums, constants, signatures, errors
  link.py           port owner, frame demux, log routing
  scan/             FILM methods, setup, teardown
  bench/
    tmc2209_shadow.py   what the PC believes each register holds
    console.py          the described surface
    checks/             declared in place, collected at import
  tools/
    fw_api_gen.py   libclang: headers in, fw_api.py out
  tests/
```

The repo root is what goes on `sys.path`, which is what makes this work.
Subsystems are then siblings: `transport.scan` and `capture.scan` are distinct
without either needing a wrapper directory, and the orchestrator reaches all
three through one path entry rather than one per subsystem.

`src/` exists to stop a test importing the working tree when it meant the
installed copy. Nothing here is ever installed for testing, so it would be
guarding the thing we do on purpose.

The cost is that project files live inside an importable package.
`CMakeLists.txt` and `flake.nix` are inert, but `tools` and `tests` are real
subpackages, so packaging this for deployment means naming what to copy rather
than copying the directory.

`link.py` sits above both API folders rather than inside either. There is one
serial port, and the argument for one link is the argument for one binding.

`librpc.so` is built beside `fw_api.py` and gitignored. The loader resolves it
next to the package, so an installed copy and a working tree resolve the same
way, with no environment variable and no branch.

## Open

1. The contract's versioning scheme.
2. Where an operator's configuration lives once bench can write it. XDG base
   directories if this runs as somebody's program, systemd's
   `ConfigurationDirectory` and `StateDirectory` if it runs as a service. The
   thing to avoid is code that hardcodes one and gets deployed under the other.
