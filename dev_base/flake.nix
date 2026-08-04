# The one nixpkgs revision. Module flakes do `nixpkgs.follows = "base/nixpkgs"`
# so they all resolve to it. To update: `nix flake update` here, then in each
# module, so their locks pick up this directory's new hash.

{
  description = "STEF - shared nixpkgs pin for all module flakes";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }: { };
}
