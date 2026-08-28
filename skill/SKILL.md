---
name: nanobanana
description: Generate and edit real images with Gemini's Nano Banana — game sprites, sprite sheets and animated GIFs, illustrated icons, textures, mockups, photo edits, background removal. Use whenever a task needs a raster image that cannot be hand-written as SVG or CSS, when asked to "make a sprite", "draw", "generate an image", "animate this character", "remove the background", "criar sprite", "gerar imagem", "desenhar", "tirar o fundo". Also use to look at what came out and iterate on it. Do NOT use for plain interface icons, logos, diagrams or charts — those are better hand-written as SVG.
---

# Nano Banana, wired in

`nanobridge` reaches Gemini's image models through the browser session that is
already signed in, so it spends the Gemini plan the account already has instead
of billing per call.

Two ways in, same engine:

- **MCP tools** (`generate_cast`, `generate_sprite`, `animate_sprite`,
  `generate_variations`, `generate_texture`, `generate_sprite_sheet`,
  `generate_image`, `generate_icon`, `edit_image`, `cut_image`, `slice_sheet`,
  `pack_atlas`, `build_normal_map`, `check_tileable`, `repair_tileable`,
  `list_atlas_formats`, `list_palettes`, `extract_palette`, `apply_palette`,
  `nanobridge_status`, `nanobridge_reset`).
  Every generating tool returns the picture back to you — look at it before
  calling the job done.
- **CLI** (`nanobridge …`) for anything scripted, batched, or run from a Makefile.

## When this is the right tool

Reach for it when the asset is **illustration**: a character, a creature, a prop,
a texture, a background, a frame of animation, a photo edit, a hero image.

**Do not reach for it for interface chrome.** A gear, a chevron, a trash can, a
brand logo, a flowchart, a chart — those want a hand-written SVG: smaller,
crisper at every size, recolourable with CSS, and diffable in git. A generated
raster icon is bigger, blurrier when scaled, and cannot follow a theme. The
generator earns its place when the drawing is beyond what you would hand-write.

## Asked for more than one sprite? Use `generate_cast`

This is the single most important thing to get right here. Characters generated
one at a time do not match — the model picks a slightly different green each
time, and the set looks assembled from separate sessions. `generate_cast` takes
the whole list, generates them together, reads one palette from the group, locks
everyone to it, and packs an atlas. It is also faster, because nothing waits in
line.

Reach for `generate_sprite` when there is genuinely one thing to draw.

## Picking the right tool

| The ask | The tool |
| --- | --- |
| several characters that belong together | `generate_cast` |
| animate something **already generated** | `animate_sprite` — not `generate_sprite_sheet`, which draws a new character from text and will not be the sprite you approved |
| a few options to choose between | `generate_variations` — returns a contact sheet to look at |
| a repeating surface | `generate_texture` — measures the seam instead of promising it |
| lighting a 2D sprite | `build_normal_map` — local, no quota |
| one sprite | `generate_sprite` |

## Doing it

```bash
nanobridge doctor                       # which backend is live, quota left
nanobridge sprite "a small knight with a blue shield" --size 160
nanobridge sheet "a green slime" --grid 4x2 \
  --action "squash down and stretch back up, a bouncy idle loop" --fps 10
nanobridge icon "a compass rose" --style flat
nanobridge edit hero.png "make the sky stormy, keep everything else"
nanobridge cast "a knight" "a rogue" "a wizard" -f godot      # one coherent set
nanobridge animate hero.png "raises its sword" --grid 4x1    # keeps THAT character
nanobridge variations "a treasure chest" -c 4                # options to pick from
nanobridge texture "cobblestone" --preview                   # seam measured
nanobridge normal hero.png                                   # local, no quota
nanobridge palettes                                          # what is built in
nanobridge cut photo.jpg --transparent --trim --size 256      # local, no quota
nanobridge slice sheet.png --grid 6x1 --size 96                # local, no quota
nanobridge atlas hero.png villain.png item.png -o game/atlas   # local, no quota
```

`atlas` (CLI) / `pack_atlas` (MCP) turns a set of separate sprites into one
sheet plus a JSON manifest of each one's rectangle — the shape a game engine
actually wants for a cast of different sprites, as opposed to `sheet`'s single
subject animated across identical frames.

Styles: `pixel` (default for sprites), `flat`, `cartoon`, `3d`, `realistic`,
`sketch` — or any free-text description.

Palettes: `pico8`, `gameboy`, `gameboy-pocket`, `cga`, `c64`, `sweetie16`,
`endesga32`, `grayscale8`, or a `.hex` file, or an inline `#RRGGBB,#RRGGBB`
list. `extract_palette` turns art you already like into one of those files.

For pixel art, prefer `--pixels N` over `--size N`: `--size` scales the image,
`--pixels` rebuilds it at exactly N art pixels so the grid actually closes.
`--zoom` scales it back up by a whole number without breaking that.

## Writing the prompt

**Name what you do not want.** The model adds a drop shadow, a patch of ground,
a border, a caption, a mockup frame — each of which ruins a sprite, and none of
which go away by asking for something "clean". The built-in templates already
carry that list; when you write a free-form `generate_image` prompt, carry it
yourself: *no shadow, no floor, no border, no frame, no text, no watermark, no
mockup, no extra objects.*

**Be concrete about the silhouette, vague about everything else.** A sprite is
read at 32 pixels and what survives is the outline. `a stocky warrior with a
round shield and a short axe` draws; `a warrior weathered by years of war` does
not.

**One subject per image.** "a knight and his horse" gives a scene that cannot be
cut into two sprites. Generate separately, then `pack_atlas`.

**Say the pose** when several sprites must match: `facing the camera`, `side
view, facing right`.

**Style is a whole sentence under the hood.** Passing free text to `style`
replaces that sentence, so include what you still want — outline weight,
palette, shading.

**Textures need a `size`.** Without it a texture is ~2048px square — a nice
picture and a useless tile. Pass 256 or 128. The resize happens before the seam
is measured, so the number describes the tile that actually ships. And say the
contrast you want: "dark dungeon floor" plus a 16-colour palette collapses into
near-black mush.

**Pixel art needs `pixels`.** The style alone gives pixel-art-*looking* art at
1024px: smooth curves pretending to be pixels. `pixels=32` resamples to a real
grid.

**Animation actions are loops.** `a walk cycle: left leg forward, passing pose,
right leg forward, passing pose` beats `walking`. Add *returning to the start*
when it should loop, or the GIF jumps. Fewer frames hold together far better —
`4x1` is reliable where `6x2` drifts, and by frame ten the character has quietly
changed.

**Reference beats description.** Once a sprite exists, never describe it again —
hand the file over (`animate_sprite`, `edit_image`) and add *keep everything
else identical*, or "add a cape" becomes "a different character, with a cape".

## When the output is wrong

- **Wrong drawing** → change the prompt. Regenerating an unchanged prompt mostly
  repeats it.
- **Right drawing, wrong crop or background** → fix it locally. `cut_image`,
  `slice_sheet`, `pack_atlas`, `build_normal_map` and `repair_tileable` cost no
  quota. Never spend a generation on what Pillow can do.
- **The model answers in words instead of drawing** → it read the prompt as a
  question. Rephrase as a description of an object. Retries already handle this.
- **Everything looks the same across attempts** → the model converges; that is
  what `generate_variations` is for.

Full guide with the reasoning: `PROMPTING.md` in the repository.

## What makes the output usable

- **Say what you do NOT want.** The prompt templates already forbid shadows,
  floors, borders, text and mockup frames, because those are what the model adds
  on its own and what makes a sprite unusable.
- **Sprites come back trimmed and transparent.** The background removal is
  border-connected, so a white eye inside a sprite survives while the white
  around it goes.
- **Grids are cut geometrically.** `--grid 4x2` cuts into 4x2 whatever the model
  drew. Look at the returned frames: if they are off-centre or misaligned, the
  model ignored the grid — change the grid or the action, do not fight the cut.
- **Iterate in one conversation.** Pass the `conversation` value back to
  `generate_image`/`edit_image` and the model keeps the same character instead
  of inventing a new one.
- **The local tools cost nothing.** `cut_image` and `slice_sheet` never touch the
  network, so post-processing a bad crop is free — regenerate only when the
  *drawing* is wrong.

## When it will not work

`nanobridge doctor` says so in one line. Almost always it is the session: sign in
at <https://gemini.google.com> in Chrome and run it again. If the MCP server has
been running a while, call `nanobridge_reset` right after signing back in —
otherwise it keeps using the old session until a generation fails and reports
it. There is no API key to paste and nothing to buy.
