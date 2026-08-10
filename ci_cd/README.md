# CI/CD
```
python -m ci_cd.run lint          format, lint and type-check
python -m ci_cd.run lint --staged the same, restricted to what is staged
python -m ci_cd.run test          every module builds and its unit tests pass
python -m ci_cd.run integration   test, plus what only makes sense across modules
python -m ci_cd.run --list        what was discovered
python -m ci_cd.run test rpc      one check, one module
python -m ci_cd.run build [mod]   build only, every module or one
python -m ci_cd.run fmt --fix     rewrite rather than report
```

`ci_cd` is a package rooted at the repository root, like every other Python
module here, so it is reached with `-m` and from that root. That one import root
is also why `pyrightconfig.json` carries no path list.

## Actions

The three correspond to the points where work moves.

| action | when | what |
|--------|------|------|
| `lint` | every commit | `fmt`, `lint` and `types` |
| `test` | reaching `develop` | `lint`, then build and unit tests, all modules |
| `integration` | reaching `main` | `test` plus `generated`, cross-module and derived docs |

- Each action runs the one below it. Reaching `main` covers everything.

- That containment catches a commit made with `--no-verify` when merges to `develop`.

- `lint` from `pre-commit` takes the staged files. From `test` it takes every
  tracked file. `types` ignores that distinction: a type error is not local to
  the file that causes it, so it always asks about whole modules.

- Which action applies is decided by where the work is going. `BRANCH_ACTION` in `actions.py` holds that table.

## Layout

Each file answers one question. Read them in this order.

| file | the question it answers | key names |
|------|------------------------|-----------|
| `paths.py` | where is everything | `ROOT`, `CICD_BUILD`, `CICD_RUNNER`, `HOOKS_PATH` |
| `ui.py` | how does a result get printed | `heading`, `report`, `skip`, `hint` |
| `discovery.py` | what counts as a module, and what is in it | `Module`, `discover` |
| `environment.py` | python to command line, and the shell each command needs | `run_command`, `run_in_module_shell`, `get_module_shell_output`, `get_git_output`, `ensure_ci_shell`, `ensure_git_hooks`, `get_current_branch`, `get_staged_files`, `get_tracked_files` |
| `tidy_db.py` | how is the firmware compile database made readable to clang | `rewritten_for_clang` |
| `checks.py` | what does one check do to one thing | `check_fmt`, `apply_fmt`, `check_lint`, `check_types`, `check_build`, `cmake`, `check_test`, `check_generated`, `check_commit_msg` |
| `actions.py` | which checks make up an action, and which branch demands which action | `lint`, `test`, `integration`, `BRANCH_ACTION`, `required_for` |
| `run.py` | entry point: what you or a hook ask of the `ci_cd` module | `parser`, `main`, `list_modules` |

The dependency direction is strictly down that list: `actions.py` imports from
`checks.py` and never the reverse, and only `run.py` imports `actions.py`. A new
check is one function in `checks.py` plus one line in `actions.py`. A new action
is one function and one entry in `ORDER`. A new branch policy is one entry in
`BRANCH_ACTION` and nothing else.

## Hooks

Four hooks, each a single `exec` into `ci_cd.run`. They hold no policy, only
the translation from git's calling convention to a command:

| hook | runs | fires |
|------|------|-------|
| `pre-commit` | `ci_cd.run lint --staged` | every commit, on the staged files only |
| `commit-msg` | `ci_cd.run commit-msg <file>` | the only moment git offers the message, so no action contains this check and nothing downstream repeats it |
| `pre-merge-commit` | `ci_cd.run verify-for <current branch>` | only when git writes the merge commit itself |
| `pre-push` | `ci_cd.run verify-for <destination refs>` | every push, asking about the destination |

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
  are idempotent, so a clone and one `python -m ci_cd.run --list` is the whole
  setup.

## Modules are discovered, not listed

A directory with a `flake.nix` is a module, and one without it only groups the
modules a level below. What a module contains decides how it is checked:

- `CMakeLists.txt` naming `project.cmake` → an ESP-IDF app, built with `idf.py`
- `test/CMakeLists.txt` → a host build, run with `ctest`
- a `host/` or root `CMakeLists.txt` naming its own `project()` → a library the
  module ships, built before any module is tested
- `pyproject.toml` → a Python package, run with `pytest`
- any `.py` file → type-checked
- `[tool.stef] generated` in `pyproject.toml` → a command that regenerates a
  committed file and fails if it moved, run by `integration`

- A module with none of these, `ci_cd`, `dev_base` and `gui` today, is listed as
  empty and skipped. Its name is still a valid commit scope.

- Nothing declares which module depends on which. Every module is built before
  any module is tested, which is enough.

- No affected-set calculation: `test` across every module takes about thirty
  seconds.

## Tools

- Each check runs inside its own module's `nix develop`, so a module declares
  what it needs and this runner only chains them. Every flake resolves nixpkgs
  through `dev_base`, so one revision builds the whole repository.

- `ci_cd` is one of those modules: `ci_cd/flake.nix` declares `ruff`,
  `basedpyright`, `clang-tools` and the rest, and `run.py` re-execs itself into
  that shell when they are not already on `PATH`.

- `basedpyright` and `ruff` read `pyrightconfig.json` and `ruff.toml` at the
  repository root.

- `clang-tidy` runs outside any shell, against one merged compile database that
  `tidy_db.py` rewrites for clang: GCC-only flags dropped, each driver asked
  where its own headers live. The firmware's entries need one thing more.
  Firmware is built by a GCC tailored to Xtensa, and upstream clang has no
  Xtensa backend to be tailored the same way, so it never predefines
  `__XTENSA__` and ESP-IDF's `xtensa/config/core.h` falls into an include path
  that does not resolve. `tidy_db.py` defines the macro for those entries. This
  buys a parse that reaches our own code, not a model of the chip.

- A C file in no database is skipped rather than guessed at, and the count says
  so.

## Commit messages

```
scope: subject
```

`scope` is a module name or one of `docs`, `meta`, `repo`. Subject line at most
72 characters.

The rule lives in `check_commit_msg` in `checks.py`.

## Formatting

Python through `ruff format`, C through `clang-format` against `.clang-format`
at the repository root. `fmt` reports, `fmt --fix` rewrites, adding
`ruff check --fix --select I` because `ruff format` leaves imports unsorted.

`fmt (c)` needs no compile database, unlike `lint (c)`, so it covers every
tracked C file whether or not that file has been built.
