# logs

Loguru configured once. Every line names the module that wrote it.

## A line

```
[INFO    ] 2026-08-22 08:22:18.719 [bench_api           ] [transport.prelink.verify_port] open load
[INFO    ] 2026-08-22 08:22:18.719 [capture.probe       ] no camera answered
```

Level, time, component, and the routine when there is one.

`as_component("capture")` binds the component, `DEFAULTS` fills it when nothing
did. `format=` is a callable because the routine bracket is per record; such a
callable must append `\n{exception}` itself.

## Sinks

`start()` puts up two and returns the file.

| sink | level | form |
| --- | --- | --- |
| `sys.stderr` | INFO | coloured |
| `state/logs/stef.jsonl` | DEBUG | one JSON object per line |

`to(sink)` adds one more. A GUI for example could take its log panel from there.

Rotation at 10 MB. `capped_at(BUDGET)` drops the oldest archives past 1 GB,
keeping the newest whatever its size.

## stdlib_intercept.py

`ccapi`, `pyserial` and `esptool` log through `logging`. `intercept_stdlib()`
replaces every root handler with one that forwards to loguru, the logger's name
becoming the component.

Two costs sit there. A `LogRecord` has no slot for `extra`, so `_attached`
subtracts the attributes `logging` sets itself. Loguru stamps a line's origin
from the stack, so `_depth_to_caller` skips the `logging` frames.

## Tests

```bash
python -m ci_cd.run test logs
```
