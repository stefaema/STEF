# GUI

One screen drives subsystems that share nothing. The screen could learn all of them, and then
every new subsystem edits the GUI and the GUI carries a device table it has no business knowing.

So it learns none of them. It reads `shared/bench_api`'s registry, serialises what it finds, and
renders declarations. Nothing under `src/` names a subsystem, a port or a register, and the day
capture is decorated it appears here with no change to this module.

## What is served

The diagnostics screen, for whatever subsystems `ROSTER` in `src/app.py` lists. Operation,
settings and the standalone log are in the rail and disabled: operation needs an orchestrator
that is not designed, and settings needs an editor for the firmware pin.

Everything a subsystem offers is a routine. The screen groups them by the category each one
declares, and gates each group on the one thing the category already says:

| panel | category | runnable when |
| --- | --- | --- |
| Link | `LINK` | always. The connect and disconnect controls themselves |
| Before connecting | `PRELINK` | the link is down, since these hold the port |
| Calls | `CALL` | the link is up |
| Routines | everything else, `SETUP` today | the link is up |

Three of those panels name the category they draw. The Routines tab takes what is left, one
labelled group per category in declaration order, so a category declared later appears there
without this module learning its name. A category with no legend in `src/text.py` is drawn under
its own name, since the alternative is a routine an operator cannot reach.

Connect is not gated on having run anything. It asks `can_connect` and shows whatever that
refuses with, so the disabled button carries the sentence naming its own remedy rather than
"run verify first". A remembered verdict would go stale on the next replug.

## The process boundary

    registry   →  backend    import, read typed objects
    backend    →  browser    JSON, so declarations are data by then

Callables never cross. A live option list crosses as the route it is fetched from and the
browser asks each time it draws the control, because ports appear when a board is plugged in and
a list baked into the page is a snapshot of process start.

Both conversions live in `bench_api` rather than here, one function per record, because they are
the contract's own vocabulary and a second screen would otherwise write them again. Coming back
the other way costs something too: JSON has one number type and no bytes, so `coerced_values`
turns what a form submits into what a declaration takes. That keeps the browser's limitations
out of every subsystem's code. The test for whether a subsystem's surface has leaked is that the
payload survives a round trip through `json`.

## One thing at a time

A bench run is a blocking generator holding the serial port, and `flash_board` holds it for tens
of seconds. There is one slot: a second attempt is refused with a sentence rather than queued,
the work runs on a thread so the loop stays free, and each outcome reaches the browser as the
step settles rather than at the end.

Two streams, both server-sent events. A run's outcomes come back on the response to the POST
that started it. Everything else, command echoes, results, log records, shares `/api/events`,
which a late listener joins with a backlog.

A run's steps reach the log through `bench_api`, which writes every run down, and not through
this module echoing them a second time. The sink here is added at `INFO`, so a step that passed
is in the file and not on the screen, and what shows is the command this module dispatched, the
run starting under it, whatever warned or failed, and the verdict.

## Language

English is the source language and every legend goes through `gettext`. The screen builds most
of itself in JavaScript, so its legends would be invisible to an extractor reading Python; they
are declared in `src/text.py` instead and handed to the page, and the browser holds only keys.
One catalog, one extraction toolchain. No `.po` files exist yet, and the untranslated path is
the identity function, so the screen reads correctly with none installed.

## Layout

| path | what it answers |
| --- | --- |
| `src/app.py` | the routes, and what a request is allowed to do |
| `src/runner.py` | the one slot, and the stream everything reports on |
| `src/stef.py` | what the whole machine is doing. Placeholder until an orchestrator says |
| `src/text.py` | every legend the browser writes |
| `src/i18n.py` | where catalogs are looked for |
| `src/templates/` | the shell the browser fills in |
| `web/src/input.css` | the design tokens and the grid utilities |
| `web/app/diagnostics.js` | the renderers, one per declared kind |

## Running it

```bash
nix develop .#gui
uvicorn gui.src.app:app --reload
```

The shell exports `STEF_HOME`, so config, state and the log file land under
`local/` rather than under this machine's XDG roots.

Restyling means rebuilding the stylesheet, which reads the template and the app script:

```bash
cd gui && tailwindcss -i web/src/input.css -o web/tailwind.css
```

## Tests

```bash
python -m ci_cd.run test gui
```
