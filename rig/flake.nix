{
  description = "STEF - The rig, its parts modelled as code and exported for fabrication";

  inputs = {
    base.url = "path:../dev_base";
    nixpkgs.follows = "base/nixpkgs";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs:
        let
          python = pkgs.python313.override {
            self = python;
            packageOverrides = import ./nix/overlay.nix;
          };

          fonts = pkgs.symlinkJoin {
            name = "stef-rig-fonts";
            paths = [ pkgs.ibm-plex pkgs.dejavu_fonts ];
          };
        in {
          default = pkgs.mkShell {
            buildInputs = [
              (python.withPackages (ps: [
                ps.build123d
                ps.yacv-server
              ]))
              pkgs.ruff
            ];

            env.STEF_RIG_FONTS = "${fonts}/share/fonts";

            shellHook = ''
              export STEF_HOME="''${STEF_HOME:-$(git rev-parse --show-toplevel)/local}"
            '';
          };
        });
    };
}
