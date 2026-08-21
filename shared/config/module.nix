{ ... }:

{
  description = "the TOML this machine is configured by, as the dictionaries a caller reads";

  python = ps: [ ps.pytest ];
}
