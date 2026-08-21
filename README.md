# STEF
Film Transport and Scanning System / Sistema de Transporte y Escaneo Fílmico

## The shells

One `flake.nix`, at the root, and one `flake.lock`. Every module declares what
it needs in its own `module.nix`, as data rather than as an assembled shell, and
the root flake turns those declarations into shells:

```bash
nix develop            # the editor shell
nix develop .#gui      # one module
```

The editor shell is the union: one interpreter carrying every Python import in
the tree, plus `ruff`, `basedpyright` and `clangd`.

A `module.nix` returns an attribute set, every field optional:

| field | what it declares |
| --- | --- |
| `description` | the line `nix eval .#modules.<system>` prints |
| `systems` | where the module builds, both Linux architectures by default |
| `python` | `ps: [ ... ]`, the interpreter's packages |
| `packages` | everything else on `PATH` |
| `env` | variables the shell exports |
| `pythonOverlay` | packages nixpkgs does not carry, added to the interpreter |
| `shell` | a shell taken whole from elsewhere, which `firmware` does |

The interpreter is 3.13, fixed there by `rig`'s CAD wheels being `cp313`.

Every shell exports `STEF_HOME`, pointing at `local/`. `shared.paths` reads it
to decide where config, state and logs go, so a shell that left it unset would
write the log file somewhere nobody thinks to look.

Updating nixpkgs is `nix flake update`, once, at the root.

## Modules

A directory holding a `module.nix` is a module; one without it only groups the
modules below it. The root flake and `ci_cd/discovery.py` walk that same rule,
so one file both declares a module's toolchain and makes it a module. `python -m
ci_cd.run --list` prints what discovery found.
