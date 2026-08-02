# Verification

One command, its tools pinned by the same flakes that build the code:

```
ci/run.py gate 1        format and lint, staged files only
ci/run.py gate 2        every module builds and its unit tests pass
ci/run.py gate 3        gate 2, plus what only makes sense across modules
ci/run.py --list        what was discovered
ci/run.py test rpc      one check, one module
```

## Gates

The three correspond to the points where work moves, per 4.2.2 of the report.

| gate | when | what | cost |
|------|------|------|------|
| 1 | every commit | `fmt`, `lint` on staged files, commit message | under a second |
| 2 | push to `develop` | build and unit tests, all modules | ~30 s |
| 3 | push to `main` | gate 2 plus cross-module and derived docs | ~30 s today |

Git has no usable pre-merge hook, so `pre-push` picks the gate from where the
work is going. Pushing a subsystem branch runs nothing: the point of a subsystem
branch is that the rest of the system may not exist yet.

## Modules are discovered, not listed

A directory with a `flake.nix` is a module, and what it contains decides how it
is checked:

- `CMakeLists.txt` naming `project.cmake` → an ESP-IDF app, built with `idf.py`
- `test/CMakeLists.txt` → a host build, run with `ctest`
- `pyproject.toml` → a Python package, run with `pytest`

Nothing enumerates the modules and nothing declares which depends on which. Both
would be second copies of what the tree already says, wrong the first time
someone forgot to update them. There is no affected-set calculation either:
gate 2 across every module takes about thirty seconds, which is not worth a
dependency graph to optimise. If that changes, the graph is already written by
the compiler and readable with `ninja -t deps`.

## Tools

Each check runs inside its own module's `nix develop`, so a module declares what
it needs and this runner only chains them. `nix develop` and not `nix run`,
because flakes only see git-tracked files and a hook has to check the work you
have not committed yet.

The one exception is `clang-tidy`, which runs outside any shell against a
rewritten copy of the firmware's compile database. The original invokes
`xtensa-esp32s3-elf-gcc`, whose flags upstream clang rejects and whose system
headers it would otherwise take from the host glibc. `tidy_db()` in `run.py`
drops the GCC-only flags and asks the cross compiler where its own headers live,
which is the command-line counterpart of the `Remove` list and `--query-driver`
that `.clangd` needs for the same reason.

## Commit messages

```
scope: subject
```

`scope` is a module name or one of `ci`, `docs`, `meta`, `repo`, `boards`.
Subject line at most 72 characters.

This is a placeholder convention, chosen because the repository is one directory
per concern and at least one existing commit already reads `firmware: ...`.
Commits written before this check exists will not pass it. To change the rule,
edit `check_commit_msg` in `run.py` and this section.

## Hooks

`.git/hooks` is not versioned, so a fresh clone would have none. Entering the
root shell points git at the tracked directory instead:

```
git config core.hooksPath ci/hooks
```

The root `flake.nix` `shellHook` does this on activation, so a clone plus
`nix develop` is all the setup there is.

## Formatting

C is not formatted. `.clang-format` at the repository root holds the style this
codebase would adopt, with `DisableFormat: true` so it stays inert, and the
reasoning is in that file. `fmt` therefore covers Python only. C is held to
`.clang-tidy` instead, which catches defects rather than whitespace.
