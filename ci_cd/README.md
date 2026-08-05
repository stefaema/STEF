# CI/CD
```
ci_cd/run.py lint          format and lint every tracked file
ci_cd/run.py lint --staged the same, restricted to what is staged
ci_cd/run.py test          every module builds and its unit tests pass
ci_cd/run.py integration   test, plus what only makes sense across modules
ci_cd/run.py --list        what was discovered
ci_cd/run.py test rpc      one check, one module
```

## Actions

The three correspond to the points where work moves.

| action | when | what |
|--------|------|------|
| `lint` | every commit | `fmt` and `lint` |
| `test` | reaching `develop` | `lint`, then build and unit tests, all modules |
| `integration` | reaching `main` | `test` plus cross-module and derived docs |

- Each action runs the one below it. Reaching `main` covers everything.

- That containment catches a commit made with `--no-verify` when merges to `develop`.

- `lint` from `pre-commit` takes the staged files. From `test` it takes every tracked file.

- Which action applies is decided by where the work is going. `BRANCH_ACTION` in `actions.py` holds that table.

## Layout

Each file answers one question. Read them in this order.

| file | the question it answers | key names |
|------|------------------------|-----------|
| `paths.py` | where is everything | `ROOT`, `CICD_BUILD`, `CICD_RUNNER`, `HOOKS_PATH` |
| `ui.py` | how does a result get printed | `heading`, `report`, `skip` |
| `discovery.py` | what counts as a module, and what is in it | `Module`, `discover` |
| `environment.py` | python to command line, and the shell each command needs | `sh`, `in_shell`, `git`, `ensure_tools`, `ensure_hooks`, `staged_files`, `tracked_files` |
| `tidy_db.py` | how is the firmware compile database made readable to clang | `rewritten_for_clang` |
| `checks.py` | what does one check do to one thing | `check_fmt`, `check_lint`, `check_build`, `check_test`, `check_commit_msg` |
| `actions.py` | which checks make up an action, and which branch demands which action | `lint`, `test`, `integration`, `BRANCH_ACTION`, `required_for` |
| `run.py` | entry point: what you or a hook ask of the `ci_cd` module | the argument parser, and nothing else of substance |

The dependency direction is strictly down that list: `actions.py` imports from
`checks.py` and never the reverse, and only `run.py` imports `actions.py`. A new
check is one function in `checks.py` plus one line in `actions.py`. A new action
is one function and one entry in `ORDER`. A new branch policy is one entry in
`BRANCH_ACTION` and nothing else.

## Hooks

Four hooks, each a single `exec` into `run.py`. They hold no policy, only the
translation from git's calling convention to a command:

| hook | runs | fires |
|------|------|-------|
| `pre-commit` | `run.py lint --staged` | every commit, on the staged files only |
| `commit-msg` | `run.py commit-msg <file>` | the only moment git offers the message, so no action contains this check and nothing downstream repeats it |
| `pre-merge-commit` | `run.py verify-for <current branch>` | only when git writes the merge commit itself |
| `pre-push` | `run.py verify-for <destination refs>` | every push, asking about the destination |

- Being bound to that moment, `pre-merge-commit` needs `merge.ff false`, which
  `run.py` sets, or a fast-forward merge slips past it.

- It buys earlier failure, not more coverage. A conflicted merge finishes
  through `git commit` and a merge made on another clone never runs it, so
  `pre-push` has to catch everything anyway. That is why it asks about the
  destination ref rather than the current branch.

- `pre-push` drains the ref lines from stdin in shell and passes them as
  arguments. `run.py` re-execs into `nix develop` when the pinned tools are
  missing, and a re-exec after reading stdin would hand the new process an empty
  one: zero refs, push waved through.

- `.git/hooks` is not versioned, so `run.py` points git at the tracked directory
  on every invocation, `core.hooksPath ci_cd/hooks` plus `merge.ff false`. Both
  are idempotent, so a clone and one `ci_cd/run.py --list` is the whole setup.

## Modules are discovered, not listed

A directory with a `flake.nix` is a module, and what it contains decides how it
is checked:

- `CMakeLists.txt` naming `project.cmake` → an ESP-IDF app, built with `idf.py`
- `test/CMakeLists.txt` → a host build, run with `ctest`
- `pyproject.toml` → a Python package, run with `pytest`

- A module with none of these, `ci_cd`, `dev_base` and `gui` today, is listed as
  empty and skipped. Its name is still a valid commit scope.

- Nothing enumerates the modules and nothing declares which depends on which.
  Both would be second copies of what the tree already says.

- No affected-set calculation either: `test` across every module takes about
  thirty seconds. If that changes, the compiler already wrote the graph, and
  `ninja -t deps` reads it.

## Tools

- Each check runs inside its own module's `nix develop`: a module declares what
  it needs, this runner only chains them. `nix develop` and not `nix run`,
  because flakes only see git-tracked files and a hook has to check work you
  have not committed yet.

- `ci_cd` is one of those modules and no more. `ci_cd/flake.nix` declares
  `ruff`, `clang-tools` and the rest, and `run.py` re-execs itself into that
  shell when they are not already on `PATH`.

- Every flake resolves nixpkgs through `dev_base`, so one revision builds the
  whole repository. Bumping it is `nix flake update` in `dev_base`, then in each
  module.

- `clang-tidy` is the exception, running outside any shell against a merged,
  rewritten copy of every compile database in the tree: the host builds under
  `.ci-build`, plus the firmware's. `rewritten_for_clang()` in `tidy_db.py`
  drops the GCC-only flags and asks each driver where its own headers live, the
  command-line counterpart of `.clangd`'s `Remove` list and `--query-driver`.

- The firmware database invokes `xtensa-esp32s3-elf-gcc`, and upstream clang has
  no Xtensa backend, so it cannot be told the target and never predefines
  `__XTENSA__`. ESP-IDF's `xtensa/config/core.h` branches on that macro into a
  fallback include path that does not resolve, so `tidy_db.py` defines it for
  those entries. Everything else about the target stays wrong: this buys a parse
  that reaches our own code, not a model of the chip.

- A C file in no database is skipped rather than guessed at, and the count says
  so. `clang-tidy` given an unknown file falls back to a bare command with no
  include paths, which fails on the first project header and says nothing
  useful.

## Commit messages

```
scope: subject
```

`scope` is a module name or one of `docs`, `meta`, `repo`. Subject line at most
72 characters.

This is a placeholder convention, chosen because the repository is one directory
per concern and at least one existing commit already reads `firmware: ...`.
Commits written before this check exists will not pass it. To change the rule,
edit `check_commit_msg` in `checks.py` and this section.

## Formatting

Python through `ruff format`, C through `clang-format` against `.clang-format`
at the repository root. Both are checked, neither is applied: `fmt` reports and
`clang-format -i` is what fixes.

`fmt (c)` needs no compile database, unlike `lint (c)`, so it covers every
tracked C file whether or not that file has been built.

Some things in this codebase are tables that happen to be written in C: the
`switch` that maps an error to its string, the register table with its access
and class columns, the bit ladders in the register codecs, the enums whose
values are pinned by the wire. Their alignment carries the meaning that a
column is a column, and no formatter setting expresses that, so each is wrapped
in `/* clang-format off */`. There are eighteen such regions; `grep -rn
"clang-format off"` lists them.

`AlignTrailingComments: Kind: Leave` for the same reason one level down. The
alternative, `Always`, realigns each run of consecutive trailing comments
separately, so a member without a comment splits one hand-made column into two
ragged ones.
