{
  description = "STEF - Operator GUI, a client of orchestrator";

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
          python = pkgs.python3.withPackages (ps: [
            ps.fastapi
            ps.uvicorn
            ps.jinja2
            ps.loguru
            ps.httpx
            ps.pytest
            ps.pytest-asyncio
            ps.pyserial
            (ps.toPythonModule pkgs.esptool)
          ]);
        in {
          default = pkgs.mkShell {
            buildInputs = [ python pkgs.gettext pkgs.tailwindcss_4 ];
          };
        });
    };
}
