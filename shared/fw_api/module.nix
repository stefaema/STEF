{ pkgs, ... }:

{
  description = "the wire contract both ends compile as a backend of the STEF transport subsystem";

  python = ps: [ ps.libclang ps.pytest ];

  packages = [ pkgs.gcc pkgs.cmake pkgs.ninja pkgs.ruff ];

  env = {
    LIBCLANG_PATH = "${pkgs.libclang.lib}/lib";
    LIBC_INCLUDE = "${pkgs.stdenv.cc.libc_dev}/include";
  };
}
