{ ... }:

{
  description = "The three subsystems of the STEF project as a single concept.";

  python = ps: [ ps.pytest ps.loguru ];
}
