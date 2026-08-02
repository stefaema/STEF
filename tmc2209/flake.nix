{
  description = "STEF - TMC2209 stepper driver library";

  inputs = {
    root.url = "path:..";
    nixpkgs.follows = "root/nixpkgs";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          buildInputs = [ pkgs.gcc pkgs.cmake pkgs.ninja ];
        };
      });
    };
}
