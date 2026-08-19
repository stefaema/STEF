# rpc

A remote procedure call protocol over a byte stream: COBS-delimited frames, CRC-16
validated, dispatched to registered handlers.

Depends on nothing, so the same sources compile for the
target, for the host tests, and for the PC side.

## Layout

| file | what it answers |
|------|-----------------|
| `cobs.h` | how does a receiver know where a frame ends |
| `crc16.h` | did the bytes survive the wire |
| `rpc_proto.h` | what both ends must agree on: frame kinds, header layouts, status bytes |
| `rpc_frame.h` | how is a header and a CRC put around a payload, and taken off |
| `rpc_dispatch.h` | how do a namespace and a method number become a call |

`rpc_proto.h` includes nothing but `stdint` and `assert`, which is what lets
every side that speaks this protocol compile the one definition.

## Boundaries

- Framing knows a frame is `[header][payload][crc]` and nothing about the
  payload, which is a span of bytes here and a struct to whoever asked for the
  call.

- Handlers are registered, not compiled in. A switch over method numbers would
  name every handler here, and linking against everything they reach.

- A status byte is split at `RPC_STATUS_TRANSPORT_BASE`: above it the transport
  answers, below it the caller does. Neither end lists the other's names.

Anything that knows about a UART, a task or a device belongs in a bind layer,
not here.

## Tests

```bash
python -m ci_cd.run test rpc
```
