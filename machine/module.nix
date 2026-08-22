{ ... }:

{
  description = "what holds the three subsystems together";

  python = ps: [ ps.pytest ps.loguru ];
}
