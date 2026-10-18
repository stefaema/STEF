# demo

A subsystem with no hardware behind it. It acts out every behaviour that the
diagnostics screen can show, so the screen and the runner can be developed and
checked without a board or a camera attached.

The machine assembles it only while `STEF_DEMO` is set:

```bash
STEF_DEMO=1 uvicorn gui.src.app:app --reload
```

## The link

The connect form picks how the demo board behaves:

| board | what happens |
| --- | --- |
| `healthy` | connects and stays up |
| `refuses` | the probe blocks, and the link stays down |
| `fails to open` | opening raises, and the link is an error |
| `dies after a while` | connects, then stops answering after `DIES_AFTER_S` |

## Tests

| test | what it shows |
| --- | --- |
| `port.NeedsThePort` | a test with `needs=DOWN`, under Before connecting |
| `outcomes.Passes` | reports, a `Result` and a measurement within limits |
| `outcomes.Warns` | a warning |
| `outcomes.FailsEarly` | a failure, with the later steps not reached |
| `outcomes.CarriesOn` | `continue_on_failure` |
| `outcomes.OutOfLimits` | measurements that fail their step |
| `outcomes.FinishesEarly` | `finish`, with a skippable step not needed |
| `outcomes.SkipsOne` | `skip`, after which the next step runs |
| `outcomes.EndsBadly` | an end step that raises, which is an error |
| `outcomes.Guarded` | `can_run`, blocked until the left drive is enabled |
| `asking.Asks` | a confirmation, a yes or no, a choice, and a timeout |
| `running.RunsLong` | a loop with `checkpoint`, for trying cancel and Stop |
| `running.Hazardous` | steps with hazards, and an end step that leaves the drive at rest |
| `running.EndsSlowly` | an end step slower than Stop waits for, for trying Stop now |

## Commands

`read_temperature`, `enable`, `set_velocity`, `jam`, `raises` and `echo_rows`.
A jammed drive ignores `stop`, so Stop and the end step of `running.Hazardous`
report it.

Every step waits `PACE_S` so that the screen visibly fills in. The tests set it
to zero.

## Tests

```bash
python -m ci_cd.run test demo
```
