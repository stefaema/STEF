{ ... }:

{
  description = "demo module: a subsystem with no hardware behind it, which acts out every diagnostics behaviour";

  python = ps: [ ps.pytest ps.loguru ];
}
