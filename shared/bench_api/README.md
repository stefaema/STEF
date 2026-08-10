# bench_api

UI-scoped: a direct channel from the screen to each subsystem, with as little
coupling as the two ends can get away with.

A subsystem gets that channel by importing `bench_api` and decorating what it
already has. Nothing is registered by hand, nothing is subclassed, nothing moves
to a new file. A decorator runs when its module is imported, so the walk is the
registration:

```python
bench_api.load("oven")
bench_api.REGISTRY.subsystem("oven").bench_tests
```

## Declarations

Each finds its subsystem from the module it was written in, so a declaration
never names its own subsystem twice.

| decorator | on | carries |
| --- | --- | --- |
| `@subsystem(id, description)` | class | the id and the prose |
| `@link(params=())` | class | the connection form, and four methods |
| `@bench_test(hazardous=False, params=())` | class or generator | a routine an operator runs |
| `@link_test(hazardous=False, params=())` | class or generator | the same, for one that runs before connecting |
| `@step` | method | a marker inside a bench test class |
| `@action(name, ...)` | function | one call, and the residue an annotation cannot carry |

Take an oven with a thermocouple on a serial port:

```python
@bench_api.subsystem("oven", "One heating element and the probe watching it.")
class Oven:
    """Owns the port and the polling behind it."""


@bench_api.link(params=(bench_api.choice("port", serial_ports),))
class OvenLink:
    def can_connect(self, port) -> Readiness: ...
    def connect(self, port): ...
    def can_disconnect(self) -> Readiness: ...
    def disconnect(self): ...


@bench_api.action("set_target", hazardous=True, params=(
    bench_api.integer("celsius", unit="C", max=300),
))
def set_target(args: TargetArgs): ...
```

`@subsystem` and `@link` sit on the subsystem's own classes, wherever those
live. The rest lives under `bench/`.

A bench test comes in two forms, a class of `@step` methods or a generator, and
`run()` yields one `Outcome` per step as the run reaches it. It lives on the
registry's record rather than on the decorated class, so both forms look the
same to whoever calls them. The docstring is the prose: first line the title,
the rest the description, for the test and for each step.

A test that needs the operator to choose something declares `params` the way
`@link` does, and the values arrive where the routine starts: the constructor in
the class form, the call in the generator one. Never at a step, so no step is
handed values it does not use, and each form has exactly one place to check the
declaration against. Declared rather than derived, because the choices a routine
offers are usually a live list of strings, and no annotation can say where that
list comes from.

A routine that finds there is nothing left to do has not failed. Raising
`Abandoned` settles the step that raised it and skips the rest, which is how a
flash says the board already carries the image without either lying that it
wrote one or failing over a healthy board.

## Forms

An annotated argument dataclass already says most of what a control needs, so
`derive.py` reads the form off it rather than making anyone write it twice:
`bool` an on-or-off, `int` a number, an `IntEnum` a pick-one, an `IntFlag` a set
of bits, `bytes` a raw field, `list[T]` a repeating group. A type nothing knows
how to draw fails at import naming the field, on the grounds that it is a type
nobody decided how to draw.

A type says what a value is, never what it means, so what a declaration adds is
whatever the type could not have said: what the number measures, what range is
real rather than merely representable, and what has to be true before the call
may be made at all. The last of those is a call rather than a value, because it
is answered when the operator is looking at the control, not when the module was
imported.

Prose travels the same way. A field's own `metadata` becomes the control's hint,
so the sentence explaining a parameter is written beside the parameter and still
reaches the screen without either side importing the other.

Options that can differ between one render and the next are given as a
zero-argument callable instead of a sequence, and called each time they are
drawn. Anything fixed at import would be a snapshot of the world as it was when
the process started.

## Layout

| file | what it answers |
| --- | --- |
| `decorators.py` | the six declarations, and the errors they raise at import |
| `registry.py` | what the decorators build, and where it lands |
| `derive.py` | how an annotated dataclass becomes the form that calls it |
| `params.py` | the six kinds of control a form is built from |
| `readiness.py` | may this proceed, and why not when it may not |
| `results.py` | what a call found, whoever made it |
| `digest.py` | what a call will put on the wire, before it goes |
| `events.py` | one record on the stream every subsystem writes to |
| `state.py` | what a subsystem is doing, and how a run turned out |
| `stef.py` | what the whole machine is doing. Placeholder until an orchestrator says |

Everything that crosses is a frozen record, so nothing here can be spelled in
`ctypes` and no subsystem hands the screen something only it can interpret.
`Readiness` is truthy when a control may be used and carries the reason when it
may not, so a disabled button explains itself. `SubsystemState` is read off the
link when asked rather than tracked beside it, since a flag maintained in
parallel is a flag that goes stale.

Five things fail at import, each because its failure mode is otherwise silence:
a declaration in a package with no `@subsystem`, a duplicate id, a
`@bench_test` class with no `@step`, a `params` entry naming a field the call
does not take, and a declared param that its receiver does not take, whether
that receiver is `connect` and `can_connect` or a routine's own constructor.

Bench test callables must not be named `test_*` or sit in a `tests/` directory,
or pytest collects them and fails on absent hardware.

## Tests

```bash
python -m ci_cd.run test bench_api
```
