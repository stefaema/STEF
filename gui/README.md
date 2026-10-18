# GUI

One screen for every subsystem. It reads the subsystems that `machine/` assembles
and renders their `shared/diagnostics` views, so nothing under `src/` names a
subsystem, a port or a register. A new subsystem appears here with no change to
this module.

## What is served

The diagnostics screen, for the subsystems that `ROSTER` in `machine/machine.py`
lists. With `STEF_DEMO` set, the demo board from `demo/` is listed too. Operation, settings and the standalone log are in the rail and disabled:
operation needs `shared/scan_api`, which is not designed yet, and settings needs
an editor for the firmware pin.

Each subsystem gets three tools:

| tool | what it shows | runnable when |
| --- | --- | --- |
| Link | the connect form, and the tests with `needs=DOWN` | always |
| Tests | every other test, grouped by the module that declares it | the test's readiness says so |
| Commands | every command, picked by group and name | the command's readiness says so |

The Implementation card shows the subsystem's prose and `facts`. While the link
is up it also shows a Stop button, which cancels the running test and calls the
subsystem's `stop`. The button is never disabled.

Connect is not gated on having run anything. The form asks the subsystem's
`probe` and shows the sentence that it refuses with.

A disabled control shows the reason from `readiness`. The routes check
readiness again before they run anything, through `run_test` and
`run_command`.

## Running a test

A test run blocks while it holds the hardware. The machine allows one activity
at a time, so a second run is refused with a sentence and not queued. The run
happens on a worker thread so the event loop stays free.

Every outcome is reported on `/diagnostics/stream/runs` as it settles. Each
record re-renders the test's head and steps and swaps them into the page out of
band. A question that a test asks arrives the same way, as a prompt inside the
test's steps, and the operator's answer goes to `POST .../tests/{key}/answer`.
The prompt is part of the test's last run, so a page reload shows it again.

Command echoes, results and log records share `/diagnostics/stream/log`, which a
late listener joins with a backlog.

## The JSON API

`/api/*` serialises the same views with `shared.diagnostics.as_json`. An input
whose options change at runtime crosses with `options` set to `null` and
`reload` set to `[subsystem, key, input]`; `/api/options/{subsystem}/{key}/{input}`
returns the options as they are now. The test for whether a subsystem's surface
has leaked is that the payload survives a round trip through `json`.

## Language

English is the source language. Every legend goes through `gettext`, or `mark`
for module constants, in `src/i18n.py`. No `.po` files exist yet, and the
untranslated path is the identity function, so the screen reads correctly with
none installed.

## Layout

| path | what it answers |
| --- | --- |
| `src/app.py` | the routes, and what a request is allowed to do |
| `src/view.py` | the labels, tones and groupings a template reads |
| `src/render.py` | template filters, and the cache of options that change at runtime |
| `src/forms.py` | a submitted form, as the values a test or command takes |
| `src/runner.py` | running one test off the loop, and the streams everything reports on |
| `src/i18n.py` | where catalogs are looked for |
| `src/templates/` | the HTML, rendered on the server and swapped in by HTMX |
| `web/app/stef.js` | icons, "show more" toggles, the copy button and the log cap |
| `web/src/input.css` | the design tokens and the grid utilities |

## Running it

```bash
nix develop .#gui
uvicorn gui.src.app:app --reload
```

The shell exports `STEF_HOME`, so config, state and the log file land under
`local/` and not under this machine's XDG roots.

Restyling means rebuilding the stylesheet, which reads the templates and the
app script:

```bash
cd gui && tailwindcss -i web/src/input.css -o web/tailwind.css
```

## Tests

```bash
python -m ci_cd.run test gui
```
