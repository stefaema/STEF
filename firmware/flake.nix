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
        # The chip-specific shells (esp32s3-idf) are deprecated and go away in
        # ESP-IDF 6.0. Same IDF version and same xtensa toolchain either way;
        # full additionally carries the RISC-V toolchain and esp-clang, which
        # an S3-only target never invokes. Switch to esp-idf-xtensa once the
        # esp-dev input is bumped to a revision that exposes it, to drop the
        # RISC-V weight without bringing the warning back.
        default = esp-dev.devShells.${system}.esp-idf-full;
      });
    };
}
