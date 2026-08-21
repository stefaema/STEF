{
  description = "STEF - Sistema de Transporte y Escaneo Fílmico";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e2587caef70cea85dd97d7daab492899902dbf5d";
    esp-dev.url = "github:mirrexagon/nixpkgs-esp-dev";
  };

  outputs = inputs@{ self, nixpkgs, ... }:
    let
      lib = nixpkgs.lib;
      systems = [ "x86_64-linux" "aarch64-linux" ];

      # ── Finding the modules ──────────────────────────────────────────────
      #
      # A directory holding a module.nix is a module; one without it only
      # groups modules, so the search descends one level into it.

      SKIP = [ "build" ".ci-build" "__pycache__" ];

      subdirs = dir:
        let entries = builtins.readDir dir;
        in lib.filter
          (n: entries.${n} == "directory"
            && !(lib.hasPrefix "." n)
            && !(lib.elem n SKIP))
          (builtins.attrNames entries);

      moduleAt = root: rel:
        let path = root + "/${rel}";
        in lib.optional (builtins.pathExists (path + "/module.nix")) {
          name = baseNameOf rel;
          inherit path;
        };

      discover = root:
        lib.concatMap
          (top:
            let direct = moduleAt root top;
            in if direct != [ ]
            then direct
            else lib.concatMap (sub: moduleAt root "${top}/${sub}")
              (subdirs (root + "/${top}")))
          (subdirs root);

      # ── What a module declared ───────────────────────────────────────────
      #
      # module.nix returns data, not an assembled shell. It has to as python3.withPackages
      # translates only once to PATH.

      declaration = pkgs: system: m:
        let d = import (m.path + "/module.nix") { inherit pkgs inputs system; };
        in {
          inherit (m) name path;
          description = d.description or m.name;
          systems = d.systems or systems;
          python = d.python or (_: [ ]);
          packages = d.packages or [ ];
          env = d.env or { };
          pythonOverlay = d.pythonOverlay or null;
          shell = d.shell or null;
        };

      # ── What every shell gets ────────────────────────────────────────────
      #
      # One place, so a module cannot be the one that forgot. STEF_HOME is
      # what shared.paths reads to put config, state and logs under local/
      # rather than under this machine's XDG roots.

      commonHook = ''
        root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
        export STEF_HOME="''${STEF_HOME:-$root/local}"
        export PYTHONPATH="$root''${PYTHONPATH:+:$PYTHONPATH}"
      '';

      forSystem = system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          all = map (declaration pkgs system) (discover ./.);
          here = lib.filter (d: lib.elem system d.systems) all;

          # One interpreter for the repository. Modules extend its package set
          # rather than picking their own, so the editor can hold every import
          # in the tree at once. 3.13 because rig's CAD wheels are cp313.
          python = pkgs.python313.override {
            self = python;
            packageOverrides = lib.composeManyExtensions
              (lib.filter (o: o != null) (map (d: d.pythonOverlay) all));
          };

          mergedEnv = ds: lib.foldl' (acc: d: acc // d.env) { } ds;

          shellFor = d:
            if d.shell != null then
              d.shell.overrideAttrs
                (old: { shellHook = (old.shellHook or "") + commonHook; })
            else
              pkgs.mkShell {
                name = "stef-${d.name}";
                buildInputs =
                  lib.optional (d.python python.pkgs != [ ])
                    (python.withPackages d.python)
                  ++ d.packages;
                env = d.env;
                shellHook = commonHook;
              };

          # The editor shell: every import in the repository resolvable by one
          # language server, and the linters CI will judge with. KiCad and the
          # ESP-IDF toolchain are deliberately absent, being weight no language
          # server reads; `nix develop .#boards` and `.#firmware` carry those.
          editor = pkgs.mkShell {
            name = "stef";
            buildInputs = [
              (python.withPackages
                (ps: lib.unique (lib.concatMap (d: d.python ps) here)))
              pkgs.ruff
              pkgs.basedpyright
              pkgs.clang-tools
              pkgs.gcc
              pkgs.cmake
              pkgs.ninja
              pkgs.gettext
              pkgs.tailwindcss_4
              pkgs.git
            ];
            env = mergedEnv here;
            shellHook = commonHook;
          };
        in
        { default = editor; } // lib.listToAttrs
          (map (d: lib.nameValuePair d.name (shellFor d)) here);
    in
    {
      devShells = lib.genAttrs systems forSystem;

      modules = lib.genAttrs systems (system:
        map (d: { inherit (d) name description systems; })
          (map (declaration nixpkgs.legacyPackages.${system} system)
            (discover ./.)));
    };
}
