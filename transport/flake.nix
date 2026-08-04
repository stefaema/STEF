{
  description = "STEF - Film transport client, a PC-side driver of the firmware";

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
          buildInputs = [ pkgs.python3 ];
        };
      });
    };
}
