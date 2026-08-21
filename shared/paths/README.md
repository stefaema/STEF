# paths

Every module that reads a config file or writes a log needs to know where those
go, and the answer differs between an install and a checkout. Deciding it in
each module means each one gets it slightly differently wrong.

One function per question instead. No I/O beyond `ensure()`, no dependency.

## The two modes

`STEF_HOME`, when it names an absolute path, puts every root under it:
`$STEF_HOME/config`, `/state`, `/firmware`. That is one directory to delete and
one to inspect, which is what a checkout wants.

Unset, each root follows its own XDG variable, or the spec's default when that
is unset too: `~/.config/stef`, `~/.local/state/stef`, `~/.local/share/stef`.

A relative value is ignored rather than resolved, the same way the XDG spec
treats one.

## What to call

| function | answers |
| --- | --- |
| `config_dir()` | where a machine's own settings live |
| `state_dir()` | where the program writes what it must remember |
| `log_dir()` | where the program writes what it wants read afterwards |
| `bench_runs_dir()` | where one bench run's own files are kept, apart from the log it shares |
| `data_dir()` | where the program keeps what it was given |
| `firmware_bins()` | where flashable images are kept, one directory per version |
| `builtin(pkg, *parts)` | one file the package ships, found through its import |
| `layered(pkg, *parts)` | the same file under both roots, shipped first and yours second |
| `readable(pkg, *parts)` | the layered paths that exist, in the order to read them |
| `ensure(path)`, `ensure_parent(path)` | the directory, made if it was missing |

`builtin` locates a package through `importlib`, so it holds whether the package
is installed or sitting in a checkout, and a caller never spells a path relative
to `__file__`. What a package ships is not meant to be edited in place, which is
what `layered` is for: the shipped file, then the user's copy over it.

`PathsError` is raised when a path is undecidable: a package that will not
import, one with no directory on disk, or `layered` given no filename.

## Tests

```bash
python -m ci_cd.run test paths
```
