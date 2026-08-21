# Rig

This module describes the physical form of the machine: the rollers that move the film,
the structure holding them, and the enclosures around the electronics and the supply.

It holds the tools to produce the blueprints that fabrication needs, whether that ends
up 3D printed, cut on a CNC, or anything else. A part is modelled once as exact
geometry, and the format is chosen at export: STEP and BREP keep real surfaces for CAM,
STL and 3MF are meshes for a slicer, DXF and SVG are 2D.

Parts are Python, not saved model files, so a dimension that follows from another one is
written that way. That is proposal Module F: the part and its geometry derive from the
same source.

| path | what it holds |
| --- | --- |
| `src/` | one module per part |
| `builds/` | exports, derived from `src/`, never edited by hand |
| `nix/overlay.nix` | the build123d packages nixpkgs does not carry |

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

```python
from yacv_server import show
show(part, names=["capstan_roller"])   # then open http://127.0.0.1:32323
```

Importing `yacv_server` starts that server as a side effect, and the process then waits
at exit for a browser to connect.
