{ ... }:

{
  description = "Log system of the STEF project";

  python = ps: [ ps.pytest ps.loguru ];
}
