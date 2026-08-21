# bench_api

One vocabulary a subsystem declares in and one screen renders. The subsystem
says what only it can know, the GUI owns the rest, and neither imports the
other.

## Declare a subsystem

A subsystem is a package. Its last name part is the id, its docstring is the
prose the screen shows, and a `state` attribute is how it reports whether it is
reachable:

```python
"""The oven.

One heating element and the probe watching it.
"""

from oven.oven import state
```

Loading it imports everything below it, so every routine declared under the
package registers on the way in:

```python
bench_api.load_subsystem("oven")
bench_api.REGISTRY.subsystem("oven").routines
```

The walk skips anything under a `tests/` directory or named `test_*`, so loading
a subsystem does not import its own test suite and the fixtures declared there
never land in the live registry.

The rule runs the other way too, and that half is a naming convention rather
than something this package enforces: a module that declares routines must not
look like a test module, or pytest collects it, imports it a second time, and
every declaration in it registers twice. That is why the prelink ladder is
`transport/bench/prelink.py` and not `bench/link_test.py`.

## Declare a bench routine

A bench routine is one thing an operator runs in order to diagnose a subsystem. It is a generator that yields one
`StepOutcome` per step:

```python
@bench_api.routine(
    category=bench_api.SETUP,
    hazardous=True,
    steps=["Profile", "Write"],
    inputs=[bench_api.integer("celsius", unit="C", max=300)],
    can_run=element_is_cold,
)
def preheat(values: dict[str, Any]) -> Iterator[StepOutcome]:
    """Preheat the oven.

    Writes one setpoint and waits for the probe to agree with it.
    """
    yield StepOutcome(PASSED, f"target {values['celsius']} C")
```

The docstring is the prose: first line the title, the rest the description. The
id is where it lives, `subsystem.module.function`, so nothing names itself
twice.

`category` says when it may run, and one state read answers for a whole screen:

| category | may run |
| --- | --- |
| `LINK` | always. These are the connect and disconnect routines themselves |
| `PRELINK` | while the link is down, since it holds the port |
| `SETUP`, `CALL` | while the link is up |

`can_run` adds a second gate, cheap enough to ask for every routine on the
screen. `can_run_with` gets the filled form and may cost a probe, so it is asked
once, when the operator submits. Both return `READY` or `blocked("why not")`,
and the sentence is what a disabled button shows.

A routine that finds nothing left to do has not failed. `Abandoned` settles the
step that raised it and skips the rest, which is how a flash reports that the
board already carries the image without lying that it wrote one.

## Declare what it takes

Six kinds, each carrying every conversion it implies: `choice`, `boolean`,
`integer`, `bitmask`, `raw_bytes`, `group`. What a declaration adds is whatever
a type could not have said, the unit, the real range, the hint.

Options that differ between one render and the next are a zero-argument callable
rather than a sequence. Anything fixed at import is a snapshot of the world as
the process started:

```python
bench_api.choice("port", serial_ports, hint="Which port the board is on.")
```

Where the values already exist as an annotated dataclass, `inputs_for` reads the
form off it and `overridden` replaces the fields the annotation could not
describe. That is how `transport/bench/calls.py` declares twenty-six firmware
methods in a loop rather than by hand.

## Run it

```python
for outcome in bench_api.run_routine(item, values):
    ...
```

Outcomes stream as the run reaches them, and the stream cannot break: an
uncaught exception becomes one failed step, and whatever was never reached
arrives as skipped. A step that yields no title takes the next one from `steps`,
so the preview an operator saw is the list that fills in.

## What a run writes down

The stream reaches whoever is consuming it, and a consumer that closes the tab
takes the only account of the run with it. So the run also writes itself down,
from `run_routine` and nowhere else: its start and what it was asked for, every
step as it settles, and how it ended. A routine that declares nothing about
logging gets all of it.

Which sink sees what is decided by weight alone, never by a filter:

| what | level | file (`DEBUG`) | screen (`INFO`) |
| --- | --- | --- | --- |
| the run started, with its values | `INFO` | yes | yes |
| a step passed or was skipped | `DEBUG` | yes | no |
| a step warned | `WARNING` | yes | yes |
| a step failed, with the reason | `ERROR` | yes | yes |
| the run ended, its verdict and cost | `INFO` and up | yes | yes |

Every line a run causes carries `routine` and `started`, the moment it began.
That pair names the run, so a stretch of wire traffic is attributable to what
caused it and anything filed under `paths.bench_runs_dir()` joins to the log
without a minted identifier. The pair is enough because one slot means no two
runs overlap.

A thread started inside a routine does not inherit the pair, so the reader
threads a link owns are matched to a run by their timestamps and not by this.

## Layout

| file | what it answers |
| --- | --- |
| `records.py` | every record that crosses, and nothing that behaves |
| `inputs.py` | the six kinds, what an annotated dataclass implies, and both conversions |
| `registry.py` | where a declaration lands, what gates it, how it is run |
| `json_helpers.py` | each record as the JSON a screen receives, one function per record |
| `run_log.py` | what every run says about itself, and the weight that decides who hears it |

What crosses is a dictionary or a frozen record, so nothing here is spelled in
`ctypes` and no subsystem hands the screen something only it can interpret.
`SubsystemState` is read off the package when asked rather than tracked beside
it, since a flag maintained in parallel goes stale.

Live options are not serialised. The control carries the route to ask again,
`/api/options/{subsystem}/{key}/{name}`, so a list that moves is fetched rather
than sent.

A declaration fails at import where its failure mode is otherwise silence: a
module under no loaded subsystem, a duplicate id, an input of a kind no control
renders, a choice with no options, a group with no columns, an override naming
no field, and a dataclass field of a type nothing knows how to draw.

## Tests

```bash
python -m ci_cd.run test bench_api
```
