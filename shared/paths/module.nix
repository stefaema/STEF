{ ... }:

{
  description = "file path aggregator. Centralizes physical file addresses by facading the sources";

  python = ps: [ ps.pytest ];
}
