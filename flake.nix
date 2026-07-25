{
  description = "STEF - shared nixpkgs pin for all module flakes";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }: { };
}
