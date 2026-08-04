{
  description = "STEF - PCB design: driver boards and carrier board";

  inputs = {
    base.url = "path:../dev_base";
    nixpkgs.follows = "base/nixpkgs";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          buildInputs = [ pkgs.python3 ];
        };
      });
    };
}
