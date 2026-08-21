# Rig

This module describes the physical form of the machine: the rollers that move the film,
the structure holding them, and the enclosures around the electronics and the supply.

It holds the tools to produce the blueprints that fabrication needs, whether that ends
up 3D printed, cut on a CNC, or anything else. A part is modelled once as exact
geometry, and the format is chosen at export: STEP and BREP keep real surfaces for CAM,
STL and 3MF are meshes for a slicer, DXF and SVG are 2D.

Parts are Python, not saved model files: the part and its geometry derive from the same source.

| path | what it holds |
| --- | --- |
| `src/` | one module per part |
| `builds/` | parts, derived from `src/`, never edited by hand |
| `builds/samples/` | coupons that prove a fit, not parts of the machine |
| `nix/overlay.nix` | the build123d packages nixpkgs does not carry |

## What gets exported

Nothing lists the parts. `scripts/discovery.py` walks `src/` and takes two names:
`build()` for a part that goes into the machine, `sample()` for a coupon used to test that everything fits.

Either may return a single part, exported as the module's own name, or a dict, whose
keys extend that name into one file per variant:

```
builds/rollers/idler_round_groove.stl
builds/samples/mounts/dc_barrel_jack.stl
```

## The shell

```bash
nix develop .#rig
python src/<part>.py
```

Entirely Nix, so there is no venv and no `pip install`. A new package goes in
`module.nix`'s `python` list, or in `nix/overlay.nix` if nixpkgs does not carry
it. That overlay extends the whole repository's interpreter, which is why the
editor shell resolves `build123d` too.

## Previewing a part

`yacv` draws in a browser, so it needs no GPU driver from Nix:

```bash
python scripts/open_viewer.py              # everything
python scripts/open_viewer.py square_band  # only names containing that
```

Then open <http://localhost:32323>, or wherever `YACV_HOST` and `YACV_PORT` point.
