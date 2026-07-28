# firmware

> Status: empty.

ESP32-S3 firmware for the film transport subsystem: three TMC2209 drivers on one
shared single-wire UART, plus per-driver STEP/DIR/EN/DIAG.

Scope: what this is, how to build, flash and test, and where the source lives.

## Documentation

One tree, one language per file. Translations are deferred: each file gets its
pair once its content freezes, and the layout for that is decided then.

One file per thesis section, so assembly is a concatenation and not a surgery.

| Path | Contents | Thesis | Language |
|---|---|---|---|
| `docs/README.md` | Architecture, then the design of each component. | Desarrollo de Firmware | English |
| `docs/api_reference.md` | Generated from the source headers by CI/CD. | Apéndice | English |
| `docs/theory.md` | What a reader must have read to follow the body. Linear, read once. | Marco Teórico | castellano |
| `docs/top-bottom-assessment.md` | Where the design stands against its targets. | never | English |
| `docs/dev_notes.md` | Bench notes. | never | English |

Hardware (carrier board, driver boards, RJ45 pinout, straps) is deliberately
**not** here. It belongs to `boards/`, not to the firmware. Until that tree
exists the material stays in `docs/dev_notes.md`.

Filenames stay English everywhere, including in the Spanish tier, so a file and
its future translation can share a name.
