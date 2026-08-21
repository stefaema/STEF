{ pkgs, ... }:

{
  description = "KiCad schematics and PCB layouts related to the STEF project";

  packages = [ pkgs.kicad ];
}
