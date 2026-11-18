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

`GuiModel` (`src/model.py`) holds the screen's state and carries out the operator's
actions. Routes call its methods and render its state. No route or template calls a
subsystem.

```
browser ──HTTP──▶ app.py ──calls──▶ GuiModel ──requests──▶ SubsystemWorker ──▶ hardware
   ▲                                   │ ▲                      one per subsystem
   └──SSE── bindings.py ◀──changes─────┘ └────────events──────────
```

- **`SubsystemWorker`** (`src/worker.py`) is the only code that calls its subsystem.
  It serves one request at a time from a queue, so two requests never use the port
  at once. A test runs on a separate thread that the worker owns, so an answer or a
  stop can still be passed on while the test runs.
- **The messages** (`src/messages.py`) between the model and a worker are two closed
  sets of dataclasses (requests to the worker, events from it). Every field holds a
  value that `as_json` can serialise, so a worker can run in a subprocess later.
- **The focus** is the machine's one-activity lock. Connecting and calling a command
  hold it until they return. Starting a test holds it until the test ends. A second
  action is refused with the holder's name. It is not queued.

### What runs when

1. `uvicorn` starts the app. `lifespan` starts the log file, the model and the
   bindings. The model assembles the roster and starts one worker per subsystem.
2. A page load renders from the model's state and sends no request to the hardware.
3. Every action posts a form. The route parses it (`src/forms.py`), calls the model
   and returns the fragment that changed.
4. A worker sends an event for every change. The model updates its state and
   publishes a `Change` on one of four channels.
5. On shutdown, `lifespan` closes the model. Running tests are cancelled and run
   their end step, then every subsystem is stopped and disconnected.

### The channels

The browser opens one SSE connection at `/diagnostics/events`. `src/bindings.py`
renders each change once into an event and sends the same text to every connection.

| channel | event | what it redraws |
| --- | --- | --- |
| log | `log` | one row of the log dock |
| link | `link` | the link marks on the subsystem tabs, the Implementation card, the stop alarm and every test's head |
| link | `link_state` | sent only when the link state changed. It makes the board of that subsystem request itself again, because its content depends on the open tool. During a connect or disconnect, one is sent when the action ends. |
| test progress | `test_progress` | one test's head and steps, and its group's mark when it ends |
| focus | `focus` | the busy line in the header |

A refused connect is kept in the model with the submitted target, so the Link panel shows the refusal until the next attempt and the form keeps the target. A link in error shows its reason.

`Linked.watch_link` reports each link change when it happens. The worker also
checks the link once a second for changes that were not reported.

## Stopping

The tool bar's Stop and a running test's Stop both call `request_stop`. A running
test is cancelled, its end step runs, then the subsystem's `stop()` runs. When the
end step takes longer than expected (30 s, unless the test's `@end` sets another
time), the card says so. For a hazardous test it also says to cut the hardware's
power.

A stop is not sent when the link is down or lost, and `StopUnconfirmed` is raised.
The board then shows a red alarm and the subsystem's tab mark turns red in every
open browser. Both stay until the operator acknowledges the alarm or a later stop
succeeds. When the link drops while a test is running, the alarm is raised at once
and the test is cancelled.

A test with `needs=DOWN` (`prelink.VerifyPort`, `prelink.FlashBoard`) holds no
link, because each of its steps opens its own short connection and closes it. Stop
cancels the test at the next step. No `stop()` is sent and no alarm is raised,
because there is no link to send it through.

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

- `tests/test_model.py` tests the model with the demo board.
- `tests/test_transport_through_the_model.py` tests transport's declarations and
  refusals with no board attached.
- `tests/test_routes.py` tests the routes on the real app.
