# RPC envelope

> Status: designed, not built.
> Normative. This file is the contract between the firmware and its clients.

Scope: the frame format and nothing else. Method names, device names, register
names, pin roles and error codes are **not** specified here. They are obtained
at runtime from `sys.describe`, so they can grow without touching this document
and cannot drift from the firmware.

This split is the whole design: the envelope is the only part a client must know
in advance, because it is what you have to speak in order to ask anything else.
Keep it small enough to stay honest.

## Framing

One JSON object per line, UTF-8, `\n` terminated. No bare newlines inside a
frame, which JSON string escaping already guarantees.

A request is at most 512 bytes. A frame over that is discarded up to the next
newline and answered `BAD_FRAME`. Replies are unbounded; `sys.describe` is the
large one.

Integers only. No floats anywhere in the schema, in either direction.

The link carries RPC and nothing else. Log output goes to UART0, so a log line
can never be mistaken for a frame.

## Requests

```json
{"id": 7, "m": "raw.read_register", "p": {"dev": "capstan", "reg": "DRV_STATUS"}}
```

| Key | Type | Meaning |
|---|---|---|
| `id` | int, 1..2³¹-1 | Client-allocated. Echoed in the reply. Monotonic, may wrap. |
| `m` | string | `namespace.method`. |
| `p` | object | Parameters. Omitted when the method takes none. |

The firmware replies to a well-formed request **exactly once**. That guarantee
is what makes a client-side timeout meaningful.

## Replies

```json
{"id": 7, "st": "OK", "value": "0x00C0010A", "fields": {"stst": true}}
{"id": 7, "st": "ERR", "err": "ACCESS"}
```

| Key | Type | Meaning |
|---|---|---|
| `id` | int or null | Echoes the request. `null` when the request was unparseable and no id could be recovered. |
| `st` | `OK` \| `WARN` \| `ERR` | Severity tier. |
| `err` | string | Present when `st` is not `OK`. Code from `sys.describe`. |
| *rest* | any | Method-specific payload. |

The tier tells a client whether the response still carries data. `WARN` carries
payload, `ERR` never does. Only `passthrough` produces `WARN`; `raw` and `smart`
validate before yielding, so a result either carries a trustworthy value or
carries nothing.

Envelope-level errors, raised before any method runs:

| Code | Cause |
|---|---|
| `BAD_FRAME` | Not valid JSON, not an object, or over the size limit. |
| `BAD_METHOD` | `m` missing or not a known method. |
| `BAD_ARGS` | `p` malformed for the named method. |

## Events

Unsolicited, sent when the firmware has something the client did not ask for.
Distinguished from a reply by the absence of `id`.

```json
{"ev": "condition", "dev": "capstan", "conditions": ["OVERTEMP_WARNING"]}
```

A client that does not care about events must still parse and discard them,
which is why `ev` is mandatory rather than inferred.

Events exist because the orchestrator runs a per-frame loop and cannot afford a
round trip to ask whether anything went wrong. The stepper is open loop: nothing
measures the shaft, so a jam loses steps silently. Driver faults and StallGuard
conditions are facts the firmware learns first and must push.

## Versioning and handshake

A client calls `sys.describe` before anything else. It returns `proto`, an
integer, alongside the vocabulary.

A client refuses to continue when `proto` is not a version it implements. There
is no negotiation and no partial compatibility: this document changing is a
breaking change, which is the reason to keep everything discoverable out of it.

`sys.describe` also returns `build`, the firmware commit, which is what the
Integrity suite records so a result names the thing it tested.

## Clients

Two, and never concurrent: the orchestrator and the bench diagnostic. Both sit
on the same PC-side client library, differing only in which namespaces they
reach for. The orchestrator uses `smart`; the diagnostic uses all three.

The port is opened exclusively (`TIOCEXCL`). A second client gets a clean
refusal instead of silently stealing bytes out of the first one's stream.
