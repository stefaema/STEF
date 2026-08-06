{
  description = "STEF - framed request/response over a serial link";

  inputs = {
    base.url = "path:../dev_base";
    nixpkgs.follows = "base/nixpkgs";
  };

  outputs = { self, nixpkgs, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAllSystems (pkgs:
        let
          unity = pkgs.fetchzip {
            url = "https://github.com/ThrowTheSwitch/Unity/archive/refs/tags/v2.6.1.tar.gz";
            sha256 = "1s0jj9f2zav49mn9ib90idcmb6hq93aczbqysn5hj6binjmrnjw3";
          };
        in {
          default = pkgs.mkShell {
            buildInputs = [ pkgs.gcc pkgs.cmake pkgs.ninja ];
            UNITY_DIR = "${unity}/src";
          };
        });
    };
}
