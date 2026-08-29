# A Fase em 3D

The same sprites and the same textures as [`../uma-fase`](../uma-fase), now in a
real 3D scene.

```bash
cd examples/fase-3d && python3 -m http.server 8757
# depois abra http://localhost:8757
```

Arrows or `WASD` to move, `space` to jump, **`L` toggles the normal map** — that
key is the whole point of the demo.

## What is honestly 3D here, and what is not

NanoBridge generates raster images. It does **not** generate meshes, and no
prompt will make it. So this is not "3D models from a prompt", and anything
claiming otherwise about a 2D image model is selling something.

What it does generate turns out to be exactly what a 3D pipeline eats:

| From the tool | Used in the scene as |
| --- | --- |
| `texture --size 256` (tileable, seam measured) | the floor and wall **albedo map**, tiled 24×24 without a visible seam |
| `normal` (derived from luminance) | the **normal map** on those materials — the light reacts to the relief |
| `cast` / `animate` sprites | **billboards**: quads that always face the camera, the way Doom drew its enemies |

Press `L` and watch the brick flatten out. That is the difference between a
normal map doing work and a texture pretending — and it is the same PNG the
`normal` command wrote, with no editing.

The tiling matters more in 3D than in 2D: the floor plane repeats the texture 24
times across, so a seam that was invisible at 1× would be a visible grid here.
It measured 1.76 / 1.78 against a threshold of 3.0, and it holds up.

## The parts the tool had no business making

The geometry, the lighting rig, the camera, the physics and the fog are plain
Three.js. Generating a gradient sky or a point light is not what an image model
is for.

## Making the assets

```bash
nanobridge texture "dungeon stone floor, worn flagstones, mid grey, clear contrast" --size 256
nanobridge texture "orange brick wall, clean mortar lines, bright warm colours" --size 256
nanobridge normal piso.png      # e parede.png — local, sem cota
```
