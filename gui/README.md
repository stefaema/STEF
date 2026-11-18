# GUI

One screen for every subsystem. It renders the `shared/diagnostics` views of the
subsystems that `machine/` assembles, so nothing under `src/` names a subsystem, a
port or a register. A new subsystem appears here with no change to this module.

## What is served

The diagnostics screen, for the subsystems that `ROSTER` in `machine/machine.py`
lists. With `STEF_DEMO` set, the demo board from `demo/` is listed too.

Operation, settings and the standalone log are in the rail and disabled:
operation needs `shared/scan_api`, which is not designed yet, and settings needs
an editor for the firmware pin.

Each subsystem gets three tools:

| tool | what it shows | runnable when |
| --- | --- | --- |
| Link | the connect form, and the tests with `needs=DOWN` | always |
| Tests | every other test, grouped by the module that declares it | the test's readiness says so |
| Commands | every command, picked by group and name | the command's readiness says so |

The Implementation card shows the subsystem's prose and `facts`.

## How it is put together

`GuiModel` (`src/model.py`) is the one object that holds what the screen shows and
does what the operator asks. Routes call its methods and render what it holds; no
route or template touches a subsystem.

```
browser ──HTTP──▶ app.py ──calls──▶ GuiModel ──requests──▶ SubsystemWorker ──▶ hardware
   ▲                                   │ ▲                      one per subsystem
   └──SSE── bindings.py ◀──changes─────┘ └────────events──────────
```

- **`SubsystemWorker`** (`src/worker.py`) is the only thing that calls its
  subsystem. It serves one request at a time from a queue, so two requests never
  share a port. A test runs on a thread the worker owns, so an answer or a stop
  still gets through while it runs.
- **The messages** (`src/messages.py`) between the model and a worker are two
  closed sets of dataclasses, requests in and events out. Every field is something
  `as_json` serialises, which is what lets a worker become a subprocess later.
- **The focus** is the machine's one-activity lock. Connecting and calling a
  command hold it for as long as they take, and starting a test holds it until the
  test ends. A second action is refused with the holder's name and not queued.

### What runs when

1. `uvicorn` starts the app, and `lifespan` starts the log file, the model and the
   bindings. The model assembles the roster and starts one worker each.
2. A page load renders from what the model holds. Nothing asks the hardware.
3. Every action posts a form. The route parses it (`src/forms.py`), calls the
   model, and returns the fragment it changed.
4. A worker sends an event whenever something changes. The model updates what it
   holds and publishes a `Change` on one of four channels.
5. On shutdown, `lifespan` closes the model: running tests are cancelled and let
   run their end step, then every subsystem is stopped and disconnected.

### The channels

The browser opens one SSE connection, `/diagnostics/events`. `src/bindings.py`
renders each change once into an event and hands the same text to every
connection.

| channel | event | what it redraws |
| --- | --- | --- |
| log | `log` | one row of the log dock |
| link | `link` | link marks on the subsystem tabs, the Implementation card, the stop alarm, every test's head |
| link | `link_state` | tells the board of that subsystem to fetch itself again, since it depends on the open tool |
| test progress | `test_progress` | one test's head and steps, and its group's mark when it ends |
| focus | `focus` | the busy line in the header |

A link is watched two ways: `Linked.watch_link` reports every change as it happens,
and the worker checks once a second for anything that was not reported.

## Stopping

The tool bar's Stop and a running test's Stop both call `request_stop`. A running
test is cancelled, its end step runs, and then the subsystem's `stop()` runs. Once
the end step is overdue (30 s, unless the test's `@end` says otherwise), the card
says so, and for a hazardous test it says to cut the hardware's power.

A stop that cannot reach the hardware raises `StopUnconfirmed`. That happens when
the link is down or lost. The board then shows a red alarm and the subsystem's tab mark turns red, on every open
browser, until the operator acknowledges it or a later stop succeeds. A link
that drops under a running test raises the same alarm at once and cancels the
test.

A test with `needs=DOWN`, such as `prelink.VerifyPort` or `prelink.FlashBoard`,
holds no link: each of its steps opens its own short connection and closes it.
Stop cancels it at the next step and calls no `stop()`, since there is no link
to send one through, and raises no alarm.

## Language

English is the source language. Every legend goes through `gettext`, or `mark`
for module constants, in `src/i18n.py`. No `.po` files exist yet, and the
untranslated path is the identity function, so the screen reads correctly with
none installed.

## Layout

| path | what it answers |
| --- | --- |
| `src/app.py` | the routes, and the app's lifespan |
| `src/model.py` | what the screen holds and what the operator can do |
| `src/worker.py` | the one thread that calls a subsystem |
| `src/messages.py` | the requests, events and channels |
| `src/bindings.py` | what each change redraws, and the browsers it goes to |
| `src/view.py` | labels, tones, groupings, form fields, and every template's context |
| `src/render.py` | template filters |
| `src/forms.py` | a submitted form, as the values a test, command or link takes |
| `src/i18n.py` | where catalogs are looked for |
| `src/templates/` | the HTML, rendered on the server and swapped in by HTMX |
| `web/app/stef.js` | icons, "show more" toggles, the copy button and the log cap |
| `web/src/input.css` | the design tokens and the grid utilities |

## Running it

```bash
nix develop .#gui
uvicorn gui.src.app:app --reload
STEF_DEMO=1 uvicorn gui.src.app:app --reload   # with the demo board
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

`tests/test_model.py` drives the model against the demo board,
`tests/test_transport_through_the_model.py` reads transport's declarations with
nothing plugged in, and `tests/test_routes.py` runs the app.
