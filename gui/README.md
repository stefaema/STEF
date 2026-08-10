# GUI

One screen drives subsystems that share nothing. The screen could learn all of them, and then
every new subsystem edits the GUI and the GUI carries a device table it has no business knowing.

So it learns none of them. It reads `shared/bench_api`'s registry, serialises what it finds, and
renders declarations. Nothing under `src/` names a subsystem, a port or a register, and the day
capture is decorated it appears here with no change to this module.

## What is served

The diagnostics screen, for whatever subsystems `SUBSYSTEMS` in `src/app.py` lists. Operation,
settings and the standalone log are in the rail and disabled: operation needs an orchestrator
that is not designed, and settings needs an editor for the firmware pin.

Three tools per subsystem, which is what the contract declares:

| tool | comes from | gated on |
| --- | --- | --- |
| Link | `@link`'s form and its four methods | nothing |
| Bench tests | `@bench_test` and `@link_test` | a link, except for link tests |
| Actions | `@action` | a link |

Connect is not gated on having run anything. It asks `can_connect` and shows whatever that
refuses with, so the disabled button carries the sentence naming its own remedy rather than
"run verify first". A remembered verdict would go stale on the next replug.

## The process boundary

    registry   →  backend    import, read typed objects
    backend    →  browser    JSON, so declarations are data by then

Callables never cross. A live option list crosses as the name it is fetched under and the
browser asks for it each time it draws the control, because ports appear when a board is plugged
in and a list baked into the page is a snapshot of process start. `wire.py` is the only module
that speaks both vocabularies, and the test for whether a subsystem's surface has leaked is that
the payload survives a round trip through `json`.

Coming back the other way costs something too: JSON has one number type and no bytes, so
`wire.arguments` coerces what a form submits into what a declaration takes. That keeps the
browser's limitations out of every subsystem's code.

## One thing at a time

A bench run is a blocking generator holding the serial port, and `flash_board` holds it for tens
of seconds. There is one slot: a second attempt is refused with a sentence rather than queued,
the work runs on a thread so the loop stays free, and each outcome reaches the browser as the
step settles rather than at the end.

Two streams, both server-sent events. A run's outcomes come back on the response to the POST
that started it. Everything else, command echoes, results, firmware log records, shares
`/api/events`, which a late listener joins with a backlog.

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
| `src/wire.py` | what crosses, both ways |
| `src/runner.py` | the one slot, and the stream everything reports on |
| `src/text.py` | every legend the browser writes |
| `src/i18n.py` | where catalogs are looked for |
| `src/templates/` | the shell the browser fills in |
| `web/src/input.css` | the design tokens and the grid utilities |
| `web/app/diagnostics.js` | the renderers, one per declared kind |

## Running it

```bash
nix develop ./gui
uvicorn gui.src.app:app --reload
```

Restyling means rebuilding the stylesheet, which reads the template and the app script:

```bash
cd gui && tailwindcss -i web/src/input.css -o web/tailwind.css
```

## Tests

```bash
python -m ci_cd.run test gui
```
