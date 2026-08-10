# tmc2209

Drives a TMC2209 stepper driver: register access over its single-wire UART, the
four control lines, and a STEP pulse train.

Depends on nothing, not even ESP-IDF, so the same sources compile for the target
and for the host tests.

## Layout

A driver is reached through three unrelated channels, and none of the three
knows the other two exist. `tmc2209_t` carries all of them, so a caller has one
device and one thing to call.

| file | what it answers |
|------|-----------------|
| `tmc2209.h` | the device object, and the component's public face |
| `tmc2209_uart.h` | the single-wire link, as a backend the caller supplies |
| `tmc2209_lines.h` | ENN, DIR, STEP and DIAG, as electrical levels |
| `tmc2209_stepgen.h` | STEP as a rate in pulses per second, not a level |
| `tmc2209_frame.h` | the UART datagram format, as pure functions over byte arrays |
| `tmc2209_reg.h` | the register table, its classification, and the field codecs |
| `tmc2209_err.h` | the failure vocabulary, one flat enum across every layer |

## Boundaries

- The three backends are interfaces, not implementations. The library emits
  bytes and asks for levels and edges; what carries them is the caller's.

- Only `tmc2209.h` may cross the three. A move sets DIR on the lines, writes
  `GCONF.shaft` over UART, then starts the pulse train, and no backend could
  have done that.

- Pulses become microsteps only at the device layer, where `CHOPCONF.mres` is
  cached. Below it, a pulse is a pulse.

- `tmc2209_reg.h` keeps two questions apart: **access** is what the driver
  permits, **class** is who can change the value, which is what decides whether
  a cached value is still true.


## Tests

```bash
python -m ci_cd.run test tmc2209
```
