{ ... }:

{
  description = "diagnostics module: the tests and commands that find out what is wrong with a subsystem";

  python = ps: [ ps.pytest ps.loguru ];
}
