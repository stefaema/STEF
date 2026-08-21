{ pkgs, ... }:

{
  description = "transport subsystem of the STEF project";

  python = ps: [
    (ps.toPythonModule (pkgs.esptool.override { python3Packages = ps; }))
    ps.libclang
    ps.loguru
    ps.pyserial
    ps.pytest
  ];

  packages = [ pkgs.gcc pkgs.cmake pkgs.ninja pkgs.ruff ];

  env = {
    LIBCLANG_PATH = "${pkgs.libclang.lib}/lib";
    LIBC_INCLUDE = "${pkgs.stdenv.cc.libc_dev}/include";
  };
}
