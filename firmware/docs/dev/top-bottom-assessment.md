# RPC

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
  `rx_got`, separates a short echo (`ECHO`) from a silent driver (`TIMEOUT`),
  and collects the reply even after a bad echo.
