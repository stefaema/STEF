# firmware

> Status: empty.

ESP32-S3 firmware for the film transport subsystem: three TMC2209 drivers on one
shared single-wire UART, plus per-driver STEP/DIR/EN/DIAG.

Scope: what this is, how to build, flash and test, and where the source lives.

## Documentation

One tree, one language per file. Translations are deferred: each file gets its
pair once its content freezes, and the layout for that is decided then.

One directory per thesis chapter, so assembly is a concatenation and not a
surgery.

| Path | Contents | Thesis | Language |
|---|---|---|---|
| `docs/theory/` | What a reader must have read to follow the body. Linear, read once. | Marco Teórico | castellano |
| `docs/appendix/` | What a reader consults to verify or reproduce. Tables, lookups. | Apéndice | castellano |
| `docs/development/` | How this firmware is built and why. | Desarrollo de Firmware | English |
| `docs/dev/` | Bench notes and roadmap. | never | English |
| `docs/design.md` | **Superseded.** The quarry the three tiers above are being cut from. Delete when empty. | never | English |

The `theory` / `appendix` split is by **how the reader uses the file**, not by
topic: front-to-back once, or looked up at random. A register table is
consult-material by definition, so it lands in `appendix/` no matter how
theoretical its subject.

Hardware (carrier board, driver boards, RJ45 pinout, straps) is deliberately
**not** here. It belongs to `boards/`, not to the firmware. Until that tree
exists the material stays in `docs/design.md` §6 and `docs/dev/notes.md`.

Filenames stay English everywhere, including in the Spanish tier, so a file and
its future translation can share a name.
