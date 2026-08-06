{
  description = "STEF - the wire contract both ends compile";

  inputs = {
    base.url = "path:../../dev_base";
    nixpkgs.follows = "base/nixpkgs";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          buildInputs = [
            (pkgs.python3.withPackages (ps: [ ps.libclang ps.pytest ]))
            pkgs.gcc
            pkgs.cmake
            pkgs.ninja
            pkgs.ruff
          ];

          env.LIBCLANG_PATH = "${pkgs.libclang.lib}/lib";
          env.LIBC_INCLUDE = "${pkgs.stdenv.cc.libc_dev}/include";
        };
      });
    };
}
