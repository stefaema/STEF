# Development Base

This meta-module holds the one nixpkgs revision the repository builds against.

Without it each module pins its own, and nothing makes two of them pick the
same. Then `shared` compiles against one glibc and `rpc` links against another,
and the failure surfaces far from its cause.

A module flake takes this directory as an input and follows it:

```nix
inputs = {
  base.url = "path:../dev_base";
  nixpkgs.follows = "base/nixpkgs";
};
```

There are no outputs. This is the revision and nothing else, so no module drags
in another module's tooling to reach it.

## Updating

```
nix flake update ./dev_base
```

Then `nix flake update` in each module, so their locks pick up this directory's
new hash. Until a module is updated it keeps building against the old revision,
which is a stale pin, not a broken one.
