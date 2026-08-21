{ pkgs, ... }:

{
  description = "Continuous Integration & Continuous Deployment";

  python = ps: [ ps.pytest ];

  packages = [
    pkgs.ruff
    pkgs.basedpyright
    pkgs.clang-tools
    pkgs.git
    pkgs.nix
  ];
}
