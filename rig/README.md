# Rig

This module describes the physical form of the machine: the rollers that move the film,
the structure itself, and the enclosures around the electronics and the supply.

It holds the tools to produce the blueprints that fabrication needs, whether that ends
up 3D printed, cut on a CNC, or anything else. A part is modelled once as exact
geometry, and the format is chosen at export: STEP and BREP keep real surfaces for CAM,
STL and 3MF are meshes for a slicer, DXF and SVG are 2D.

Parts are Python: the part and its geometry derive from the same source.

| path | what it holds |
| --- | --- |
| `src/` | one module per part |
| `out/` | parts, derived from `src/`, never edited by hand |
| `out/samples/` | coupons that prove a fit, not parts of the machine |
| `materials.py` | the print materials a part's allowances can be given for |
| `nix/overlay.nix` | the build123d packages nixpkgs does not carry |

## What gets exported

`discovery.py` walks `src/` and takes two names:
`build()` for a part that goes into the machine, `sample()` for a coupon used to test that everything fits.

Either may return a single part, exported as the module's own name, or a dict, whose
keys extend that name into one file per variant:

```
out/samples/mounts/dc_barrel_jack.stl
```

## The shell

```bash
nix develop .#rig
python src/<part>.py
```

Entirely Nix, so there is no venv and no `pip install`. A new package goes in
`module.nix`'s `python` list, or in `nix/overlay.nix` if nixpkgs does not carry
it. That overlay extends the whole repository's interpreter, which is why the
repository shell resolves `build123d` too.

`rig` is a package rooted at the repository root, so `-m` resolves it
regardless of whether the shell's `cwd` is the repository root or `rig/` itself.

## Building

```bash
python -m rig.build                       # every part under src/, as 3mf
python -m rig.build mounts                # only src/mounts
python -m rig.build mounts --format stl   # comma-separated: stl, 3mf
python -m rig.build mounts --material petg
python -m rig.build clean                 # empty out/, nothing rebuilt
python -m rig.build check                 # build every part, report invalid solids, export nothing
```

## Material

Geometry doesn't change with material, but a few small allowances do: a cutout's
clearance around a connector, a rib's press-fit interference, a wall's thickness against
bowing. `materials.py` names the materials; a module under `src/` that has one of these to
give declares it as a `dict[Material, float]` next to the constant it replaces, and its
`build()`/`sample()` takes a `material: Material = Material.PLA` parameter. `discovery.py`
passes `--material` through to any convention function that declares the parameter, and
calls the rest as before.

PLA's values are what the part was actually printed and fitted with. PETG's are only
filled in once a print confirms them; until then they equal PLA's.

## Previewing a part

`yacv` draws in a browser, so it needs no GPU driver from Nix. Viewing is scoped to one
category under `src/` at a time, both so the browser isn't laying out every part in the
repository and so a category still mid-rewrite (`rollers` today) can't keep the others
from showing:

```bash
python -m rig.view mounts               # everything under src/mounts
python -m rig.view rollers square_band  # only rollers/ names containing that
python -m rig.view mounts --material petg
```

Then open <http://localhost:32323>, or wherever `YACV_HOST` and `YACV_PORT` point.
