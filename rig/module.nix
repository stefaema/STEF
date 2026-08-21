{ pkgs, ... }:

let
  fonts = pkgs.symlinkJoin {
    name = "stef-rig-fonts";
    paths = [ pkgs.ibm-plex pkgs.dejavu_fonts ];
  };
in
{
  description = "The STEF project rig: its parts modelled as code and exported for fabrication";

  # The CAD wheels are cp313 x86_64 only, which is what fixes the repository's
  # interpreter at 3.13.
  systems = [ "x86_64-linux" ];

  pythonOverlay = import ./nix/overlay.nix;

  python = ps: [ ps.build123d ps.yacv-server ];

  packages = [ pkgs.ruff ];

  env.STEF_RIG_FONTS = "${fonts}/share/fonts";
}
