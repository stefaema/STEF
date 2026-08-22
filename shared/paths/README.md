# paths

Every module that reads a config file or writes a log needs to know where those
go, paths do the plumbing.

No I/O beyond `ensure()`, no dependency.

## The two modes

`STEF_HOME`, when it names an absolute path, puts every root under it:
`$STEF_HOME/config`, `/state`, `/firmware`. This was originally intended for the development stage.

Unset, each root follows its own XDG variable, or the spec's default when that
is unset too: `~/.config/stef`, `~/.local/state/stef`, `~/.local/share/stef`.

A relative value is ignored rather than resolved.

## Functions

| function | with `STEF_HOME` | without |
| --- | --- | --- |
| `config_dir()` | `$STEF_HOME/config` | `$XDG_CONFIG_HOME/stef` |
| `state_dir()` | `$STEF_HOME/state` | `$XDG_STATE_HOME/stef` |
| `data_dir()` | `$STEF_HOME/data` | `$XDG_DATA_HOME/stef` |

Configuration is edited by hand, state is written by the program and survives a
restart, data is formatted information that is given or offered by the program.

Everything else hangs off those three:

| function | resolves to |
| --- | --- |
| `log_dir()` | `state_dir() / logs` |
| `bench_runs_dir()` | `data_dir() / bench_runs`, one directory per run |
| `firmware_bins()` | `data_dir() / firmware`, one directory per version |

And the files a package ships with:

| function | resolves to |
| --- | --- |
| `builtin(pkg, *parts)` | `<pkg>/builtin/<parts>` |
| `layered(pkg, *parts)` | both copies: the shipped one, then `config_dir() / <parts>` |
| `readable(pkg, *parts)` | whichever of those two exist, in the order to read them |
| `ensure(path)`, `ensure_parent(path)` | the same path, with its directory created |

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
