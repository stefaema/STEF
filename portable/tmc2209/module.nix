{ pkgs, ... }:

let
  unity = pkgs.fetchzip {
    url = "https://github.com/ThrowTheSwitch/Unity/archive/refs/tags/v2.6.1.tar.gz";
    sha256 = "1s0jj9f2zav49mn9ib90idcmb6hq93aczbqysn5hj6binjmrnjw3";
  };
in
{
  description = "TMC2209 stepper driver library";

  packages = [ pkgs.gcc pkgs.cmake pkgs.ninja ];

  env.UNITY_DIR = "${unity}/src";
}
