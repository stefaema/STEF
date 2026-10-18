# diagnostics

This package defines the tests and commands that find out what is wrong with a
subsystem. Each subsystem declares its own tests and commands. The GUI renders
all of them the same way, so it does not import any subsystem.

## Contracts

| contract | lives in | what it adds |
| --- | --- | --- |
| `Subsystem` | `shared/subsystem` | identity, config, link state, `stop`, `facts` |
| `Linked[Target]` | `shared/subsystem` | connect, disconnect and the connection handle |
| `Diagnosable` | `shared/diagnostics` | tests, commands, readiness, running them, last results |

`shared/subsystem` also holds the records that both packages use: `Input` and
its six kinds, `Option`, `Readiness`, `Result`, `Level` and `Table`.
`shared/diagnostics` depends on `shared/subsystem`, and not the other way
round.

A subsystem is one class that inherits the contracts that it needs:

```python
class Oven(Linked[str], Diagnosable):
    safe_state = "element off"
    target = choice("port", serial_ports)
    tests = (Preheat, ProbeAgrees)
    commands = (set_element,)
```

The package exports this class as `SUBSYSTEM`. The machine creates one
instance at startup with `SUBSYSTEM(package)`, where `package` is the imported
package module.

## `Subsystem`

```python
class Subsystem:
    id: str
    summary: str
    description: str
    config: SubsystemConfig
    safe_state: ClassVar[str] = ""

    def link_state(self) -> LinkState
    def link_reason(self) -> str | None
    def stop(self) -> None
    def cancel(self) -> None
    def facts(self) -> Result | None
```

`id` is the last part of the package name. `summary` and `description` come
from the package docstring. `config` reads the files under the package's own
config folder.

`link_state` returns `DOWN` unless the subsystem is `Linked`. `link_reason`
explains an `ERROR`, and is `None` otherwise.

`stop` puts every device into `safe_state`. It tries every device before it
raises, and the exception names each device that it could not confirm. It can
be called at any time. Calling it on hardware that is already safe does nothing
harmful. The default does nothing.

`cancel` ends whatever the subsystem is running and returns when it has ended.
The default does nothing.

The GUI's stop action calls `cancel`, then `stop`. Tests never call `stop`
automatically.

`facts` returns what the connected device reports about itself, such as a
version, a model or a device table. The GUI shows it under the summary. The
default returns `None`.

## `Linked[Target]`

```python
class Linked[Target](Subsystem):
    target: ClassVar[Input]

    def connect(self, target: Target) -> None
    def disconnect(self) -> None
    def handle(self) -> Handle

    def probe(self, target: Target) -> Readiness
    def _open(self, target: Target) -> Handle
    def _close(self, handle: Handle) -> None
    def _alive(self, handle: Handle) -> bool
```

`Target` is the type of the value that `connect` takes. A subsystem fills it
in when it inherits, as in `Linked[str]` for a port name.

The subsystem implements `probe`, `_open` and `_close`. `_alive` returns true
by default. `target` is the input that the connect form shows.

`connect` raises `NotReady` if the link is up or already connecting.
Otherwise it reports `LINKING`, calls `probe`, and raises `NotReady` if the
probe blocks. Then it calls `_open`. If opening fails, the state becomes
`ERROR` with the exception as the reason, and the exception is raised again.

`link_state` returns `UP` when there is a handle and `_alive` returns true. If
there is a handle and `_alive` returns false, it returns `ERROR`.

`disconnect` calls `cancel`, then `stop`, then `_close`. The state is `DOWN`
afterwards, even if `stop` or `_close` raises. The first exception is raised
again after the link is closed.

`handle` returns the open connection. It raises `NotLinked` if the link is
down.

## `Diagnosable`

```python
class Diagnosable(Subsystem):
    tests: ClassVar[tuple[type[Test], ...]] = ()
    commands: ClassVar[tuple[Command, ...]] = ()

    def readiness(self, key: str, operator: bool = True) -> Readiness
    def run_test(self, key: str, submitted: Mapping, report: Report,
                 operator: bool = False) -> RunView
    def run_command(self, key: str, submitted: Mapping) -> Result
    def answer(self, submitted: Any) -> None
    def options(self, key: str, input_name: str) -> tuple[dict, ...]
    def view(self, operator: bool = True) -> SubsystemView
```

The subsystem lists its tests and commands in `tests` and `commands`. The GUI
shows them in that order. Test keys and command keys share one namespace, and
a duplicate raises `DeclarationError` when the class is created.

## Tests

A test answers whether some part of the hardware works. It is a class whose
methods are its steps:

```python
class Preheat(Test[Oven]):
    """Preheat the oven.

    Writes one setpoint and waits for the probe to agree with it.
    """

    inputs = (integer("celsius", unit="C", max=300),)
    smelled = boolean("smelled", hint="Can you smell burning?")

    @classmethod
    def can_run(cls, oven: Oven) -> Readiness:
        return READY if oven.element_is_cold() else blocked("the element is hot")

    @step("Write setpoint", hazard="switches the element on")
    def write(self) -> None:
        self.sub.handle().set_point(self.values["celsius"])

    @step("Wait for the probe")
    def wait(self) -> None:
        target = self.values["celsius"]
        reading = self.sub.handle().wait_stable()
        self.measure("probe", reading, unit="C", low=target - 5, high=target + 5)
        if self.ask(self.smelled):
            self.warn("the operator smelled burning")

    @end("Element off")
    def element_off(self) -> None:
        self.sub.handle().set_point(0)
```

### What a test declares

- The class docstring gives the title (first line) and the description (the
  rest).
- The key is `group.Name`, where the group is the last part of the module name
  that the test is written in, and `Name` is the class name.
- `inputs` is the form that the operator fills in before the run.
- Any other class attribute that is an `Input` is a question that a step can
  ask during the run.
- `needs` is the link state that the test requires: `Needs.UP` (default),
  `Needs.DOWN` or `Needs.ANY`. A test that opens the port itself uses `DOWN`.
- `can_run(subsystem)` blocks the test for a reason other than the link. The
  default returns `READY`.
- `Test[Oven]` types `self.sub` as the concrete subsystem, so a step can call
  `self.sub.handle()` and any other method that `Oven` defines.

### Steps

`@step(title)` makes a method a step. A method docstring, if there is one, is
the step's description.

| argument | meaning |
| --- | --- |
| `hazard` | a sentence that says what the step does to the hardware |
| `skippable` | the step may not run, and skipping it is a normal outcome |
| `continue_on_failure` | if the step fails, the next step still runs |

`@end(title)` makes a method the test's end step. A test has at most one, and
a subclass may replace the one that it inherits. The end step always runs: after
the steps pass, after a failure, after `finish` and after a cancel. Its
outcome is shown apart from the other steps, as how the test left the
hardware. A test without an end step simply ends after its last step.

The preview that the GUI shows before a run is the list of collected steps, so
a step's title is written only once.

### Inside a step

| call | effect |
| --- | --- |
| return normally | the step passes |
| raise | the step fails, with the exception as the detail |
| `raise Failed(detail, result=None)` | the step fails with this detail and `Result` |
| `self.report(detail, result=None)` | sets the step's detail and attaches a `Result` |
| `self.warn(detail, result=None)` | the same, and the step passes with a warning |
| `self.measure(name, value, unit=, low=, high=, expected=)` | records a value and its limits |
| `self.finish(detail, status=PASSED, result=None)` | settles this step and skips the remaining steps |
| `self.skip(detail)` | skips this step, and the next step still runs |
| `self.checkpoint()` | raises `Cancelled` if the run was cancelled |
| `self.ask(question, timeout=120)` | asks the operator and returns the converted answer |

All measurements are recorded. If any measurement is outside its limits, the
step fails when it returns.

`self.values` holds the submitted values, converted to Python types. Steps can
leave state on `self` for later steps, because the runner creates one instance
of the test for each run.

A step whose count depends on runtime data, such as one write per binary in a
release, is one step that reports each item as a row of its `Result` table.

### Questions

A question is an `Input` declared on the test class. `confirmation(text)`
declares a question whose only answer is Continue.

`self.ask(question)` blocks the step. The runner reports a `Prompt` through
`report` and waits until `answer` is called. The answer is converted by the
question's kind and recorded in the step's outcome.

If no answer arrives within `timeout` seconds, the step is cancelled with "no
answer within N s" and the run ends as if it had been cancelled: the remaining
steps are skipped and the end step runs. If the run is cancelled while the question is open, `ask` raises
`Cancelled`.

A test that declares questions needs an operator. `readiness` blocks it with
"needs an operator" when `operator` is false.

### Reusing steps

Steps that several tests share go in a base class:

```python
class ElementReady(Test[Oven]):
    @step("Identify")
    def identify(self) -> None: ...

    @step("Element on", hazard="switches the element on")
    def element_on(self) -> None: ...

    @end("Element off")
    def element_off(self) -> None: ...


class HoldTemperature(ElementReady):
    """Hold a temperature for one minute."""

    @step("Hold")
    def hold(self) -> None: ...
```

Steps from a base class come first, in the base's definition order. A
subclass that defines a method with the same name as a base step replaces that
step in place.

### How a test runs

```python
oven.run_test("heat.Preheat", submitted, report)
```

`report` is called with each `StepOutcome` as it settles, and with each
`Prompt` as it opens. `run_test` returns the finished `RunView`. It raises
`NotReady` if readiness is blocked, and does not raise after the run has
started.

1. The submitted values are converted to Python types according to `inputs`.
2. The steps run in definition order. The first failure stops them, unless the
   failing step has `continue_on_failure`.
3. The end step runs, whatever happened before it. If it raises, its status is
   error.

`cancel` takes effect between steps, at the next `self.checkpoint()`, or in an
open `self.ask`. The current step is marked cancelled, the remaining steps are
skipped, and the end step runs. A step that does neither finishes first, and
the next one is skipped. Either way, the run's verdict is cancelled unless a
step failed or errored.

The run is stored as the test's last result from its first step on, so the
GUI can read it while the test is running. Last results are kept in memory.

### Outcomes

```python
StepOutcome(step, status, detail="", skipped=None, result=None,
            measurements=(), answers=(), end=False)
Measurement(name, value, unit=None, low=None, high=None, expected=None)
Prompt(test, step, question, timeout)
```

| status | meaning |
| --- | --- |
| passed | the step returned normally and every measurement was within limits |
| warned | the step called `warn` |
| failed | a step raised, or a measurement was outside its limits |
| error | the end step raised |
| cancelled | the run was cancelled while this step ran, or its question was not answered in time |
| skipped | the step did not run; `skipped` says why |

`skipped` is one of:

| reason | when |
| --- | --- |
| `NOT_NEEDED` | the test called `finish` or `skip` |
| `NOT_REACHED` | an earlier step failed, or finished as failed |
| `CANCELLED` | the run was cancelled |

The run's verdict is its worst status, in the order error, failed, cancelled,
warned, passed, skipped. A cancelled run is at least cancelled, even when the
cancel landed between steps. An error in the end step is worse than a failure, because the
hardware may still be on.

A test that readiness blocks does not run, so it has no outcomes. Its
readiness carries the reason.

## Commands

A command is one call that returns a reply. A reply has no verdict, and a
command has no end step: running `enable` from a command is meant to leave the
hardware enabled.

```python
@dataclass(frozen=True)
class Command:
    group: str
    name: str
    title: str
    description: str
    call: Callable[[Sub, Values], Result]
    inputs: tuple[Input, ...] = ()
    needs: Needs = Needs.UP
    hazard: str | None = None
    can_run: Callable[[Sub], Readiness | None] | None = None
```

`@command(...)` declares one command from a function, and takes its group from
the module, its name from the function, and its title and description from the
docstring:

```python
@command(hazard="switches the element on or off")
def set_element(oven: Oven, values: Values) -> Result:
    """Switch the element."""
```

A family of commands, such as one per method of an API, is built by calling
`Command(...)` in a loop. `inputs_for` derives the inputs from an annotated
dataclass.

`run_command(key, submitted)` checks readiness, converts the values, calls the
command and returns its `Result`. The reply is stored as the command's last
result. If the command raises, `run_command` returns a `Result` with level
error.

## Readiness

Tests and commands share the same rules. `readiness` checks the following, in
this order:

1. whether a test is already running on this subsystem
2. whether the link state matches `needs`
3. whether `can_run(subsystem)` blocks
4. for a test with questions, whether there is an operator

It returns `READY` or `blocked("reason")`. The GUI shows the reason on the
disabled control. `run_test` and `run_command` check readiness again before
they run.

The machine allows one activity at a time. That check is in `machine`. The
stop action takes no part in either check.

## Inputs

There are six kinds: `choice`, `boolean`, `integer`, `bitmask`, `raw_bytes`
and `group`. A declaration can add a unit, a range and a hint.

When the options change at runtime, pass a function that takes the subsystem:

```python
choice("probe", lambda oven: oven.probes(), hint="Which probe.")
```

`inputs_for` creates the inputs from an annotated dataclass. `overridden`
replaces some of those inputs by name.

Each kind is one entry in a table of three functions. They check the
declaration, give the blank value, and convert a submitted value.

## Results

```python
Result(level, summary, note=None, raw=None, image=None, fields=(), table=None)
```

`level` is ok, warn or error. A step attaches a `Result` with `report` or
`warn`, and a command returns one.

## Views

The GUI reads these frozen records. The HTML pages and the JSON API are both
built from them, and `as_json` turns any of them into JSON.

```python
SubsystemView(id, summary, description, facts, safe_state, link, running,
              tests, commands)
LinkView(state, reason, target)
TestView(key, group, title, description, inputs, needs, readiness, steps,
         end, hazardous, last)
StepView(title, description, hazard, skippable)
CommandView(key, group, title, description, inputs, needs, hazard,
            readiness, last)
RunView(key, started, values, outcomes, verdict, running, cancelled, prompt)
InputView(name, kind, hint, unit, min, max, options, reload, columns)
```

`link` is `None` when the subsystem is not `Linked`. `running` is the key of
the running test, or `None`.

`TestView.steps` is the preview of the steps, and `TestView.end` is the end
step's preview, or `None`.

When an input's options change at runtime, `options` is `None` and `reload`
holds `(subsystem, key, input)`. The GUI builds the URL from that tuple.

`RunView.verdict` is `None` while the run is going. `RunView.prompt` is the
open question, or `None`.

## Run log

`run_test` logs every run, so a test does not log its own start, steps or end.

| what | level | file (`DEBUG`) | screen (`INFO`) |
| --- | --- | --- | --- |
| run started, with its values | `INFO` | yes | yes |
| step passed or skipped | `DEBUG` | yes | no |
| step warned | `WARNING` | yes | yes |
| step failed or errored, with the reason | `ERROR` | yes | yes |
| run ended, with verdict and duration | `INFO` and up | yes | yes |

Every line carries `routine` and `started`, which together identify the run.
A thread that a test starts does not carry them.

## Subsystem-specific code

Code that only one subsystem needs stays in that subsystem, for example
firmware flashing, camera discovery or datasets. The GUI sees that code
through tests, commands, `probe` results, option functions, `Result` and
`facts`.

Something moves into `shared/` when a second subsystem needs it, or when the
GUI needs a new control, gate or state for it.

## Extending

| to add | change |
| --- | --- |
| a subsystem | one class, which inherits `Linked` only if it has a connection |
| a test | one class, plus one entry in `tests` |
| a command | one function, plus one entry in `commands` |
| an input kind | one entry in the kind table, plus one template |
| a result field | one field on `Result`, plus one template |
| a precondition other than the link | `can_run` |
| another front end | nothing: it uses the same views and methods |

`StepStatus`, `SkipReason`, `LinkState` and `Needs` have fixed values. Adding a
value to any of them is a design change.

The step, end and outcome rules follow the semantics of pytest and OpenHTF.
When a new case comes up, check how those two handle it first.

These declaration errors raise when a class is created or a module is
imported:

- a duplicate test or command key in one subsystem
- a duplicate step title in one test
- a second end step in one class
- an unknown input kind
- a choice or bitmask with no options
- a group with no columns
- an override for a field that does not exist
- a dataclass field whose type has no matching input kind

## Tests

```bash
python -m ci_cd.run test diagnostics
```
