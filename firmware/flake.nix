{
  description = "STEF - ESP32 firmware driving the TMC2209 steppers over UART/STEP-DIR";

  inputs = {
    root.url = "path:..";
    nixpkgs.follows = "root/nixpkgs";
    esp-dev.url = "github:mirrexagon/nixpkgs-esp-dev";
  };

  outputs = { self, nixpkgs, esp-dev, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
    in {
      devShells = nixpkgs.lib.genAttrs systems (system: {
        default = esp-dev.devShells.${system}.esp32s3-idf;
      });
    };
}
