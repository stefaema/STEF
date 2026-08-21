{ ... }:

{
  description = "bench module: how the STEF project handles module bench-testing, debugging, and diagnosis, as an API";

  python = ps: [ ps.pytest ps.loguru ];
}
