# Modules do `nixpkgs.follows = "root/nixpkgs"` so they all resolve to one rev.
# Exports the CI shell. To update: `nix flake update` here, then in each module.

{
  description = "STEF - shared nixpkgs pin for all module flakes";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          buildInputs = [ pkgs.python3 pkgs.ruff pkgs.clang-tools pkgs.git pkgs.nix ];

          shellHook = ''
            root=$(git rev-parse --show-toplevel 2>/dev/null) || root=""
            if [ -n "$root" ] && [ "$(git config core.hooksPath || true)" != "ci/hooks" ]; then
              git config core.hooksPath ci/hooks
              git config merge.ff false
              echo "hooks installed: core.hooksPath -> ci/hooks, merge.ff off"
            fi
          '';
        };
      });
    };
}
