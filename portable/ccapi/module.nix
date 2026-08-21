{ ... }:

{
  description = "a client for Canon's Camera Control API";

  python = ps: [ ps.pytest ps.requests ];
}
