# Modules do `nixpkgs.follows = "root/nixpkgs"` so they all resolve to one rev.
# Exports nothing. To update: `nix flake update` here, then in each module.

{
  description = "STEF - shared nixpkgs pin for all module flakes";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }: { };
}
