# bench_api

One screen drives subsystems that share nothing: different links, different vocabularies,
different ways of failing. If the screen learns all of them, every new subsystem edits the
GUI. `bench_api` is the one vocabulary they all speak, so the screen renders declarations
and knows none of them. The subsystem declares what only it can know, and everything else
is the GUI's.

Records, enums and six decorators. No I/O, no third-party dependency, and no import of any
subsystem: a declaration imports `bench_api`, and `bench_api` imports nothing back.

## Declarations

Each finds its subsystem from the module it was written in, so a declaration never names
its own subsystem twice.

| decorator | on | carries |
| --- | --- | --- |
| `@subsystem(id, description)` | class | the id and the prose |
| `@link(params=())` | class | the connection form, and four methods |
| `@bench_test(hazardous=False)` | class or generator | a routine an operator runs |
| `@link_test` | class or generator | the same, for one that runs before connecting |
| `@step` | method | a marker inside a bench test class |
| `@action(name, ...)` | function | one call, and the residue an annotation cannot carry |

`@step` marks and `@bench_test` collects, since the class does not exist while its body
runs. `run()` yields one `Outcome` per step as the run reaches it, and lives on the
registry's record rather than on the decorated class, so the class form and the generator
form look the same to whoever calls them.

## Forms

`params_for()` turns a call's annotated argument dataclass into one `Param` per field:
`list[T]` a `group`, `bool` a `boolean`, an `IntFlag` a `bitmask`, an `IntEnum` a `choice`,
`bytes` a `raw_bytes`, `int` an `integer`. Anything else fails at import naming the field,
because a type this cannot draw is one nobody decided how to draw.

So a subsystem declares only the residue: units, real bounds, hazard, preconditions and
digests, which `with_declared()` puts in the slots they name. A field carrying
`metadata["doc"]` derives that as its hint, which is how prose authored at the source
reaches the screen without either side importing the other.

## What crosses

`Readiness` answers whether something may proceed and why not when it may not, truthy when
it may. `Outcome` is how one step settled, `Result` one vocabulary for what any call found,
`Digest` what a call will put on the wire before it goes, and `Event` one record on the log
every subsystem writes to. All plain data, so nothing the backend serialises can be spelled
in `ctypes`. `SubsystemState` is read off the link rather than tracked beside it, and
`stef.py`, which says what the whole machine is doing, is a placeholder until whatever
coordinates the subsystems exists.

The rest fails at import, each because its failure mode is otherwise silence: a declaration
in a package with no `@subsystem`, a duplicate id, a `@bench_test` class with no `@step`, a
`params` entry naming a field the call does not take, and a `@link` param that `connect`
and `can_connect` do not.

## How a module declares

`@subsystem` and `@link` sit on the subsystem's own classes, wherever those live. Only what
exists purely to be rendered lives under `bench/`.

```python
@bench_api.subsystem("rig", "One board, and the three drivers behind it.")
class Rig:
    """Owns the link and the threads behind it."""


@bench_api.link(params=(bench_api.choice("port", serial_ports),))
class RigLink:
    def can_connect(self, port) -> Readiness: ...
    def connect(self, port): ...
    def can_disconnect(self) -> Readiness: ...
    def disconnect(self): ...


@bench_api.bench_test(hazardous=True)
class Ramp:
    """Acceleration ramp.

    Emits a profile and compares the declared count against the emitted one.
    """

    @bench_api.step
    def enable(self, bench):
        """Enable the stage."""


@bench_api.action("raw.move", hazardous=True, params=(
    bench_api.integer("cruise_pps", unit="pps", max=3200),
))
def move(args: MoveArgs): ...
```

A decorator runs when its module is imported, so the walk is the registration:

```python
bench_api.load("rig")
bench_api.REGISTRY.subsystem("rig").bench_tests
```

Bench test callables must not be named `test_*` or sit in a `tests/` directory, or pytest
collects them and fails on absent hardware.
