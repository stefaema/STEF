{ ... }:

{
  description = "STEF film capture subsystem";

  python = ps: [ ps.pytest ps.requests ps.loguru ];
}
