# NanoBridge

[![tests](https://github.com/NspxMiguel/NanoBridge/actions/workflows/tests.yml/badge.svg)](https://github.com/NspxMiguel/NanoBridge/actions/workflows/tests.yml)

Gemini's **Nano Banana** image generation, wired into agents as an **MCP server**
and a **CLI** — using the Gemini plan the account already has, not a per-image
bill.

```bash
nanobridge sprite "a small knight with a blue shield and a silver sword" --size 160
```

<p align="center">
  <img src="assets/knight.png" width="160" alt="generated knight sprite">
  <img src="assets/slime.gif" width="160" alt="generated slime animation">
</p>

Both of those came out of the commands in this README — the sprite already
trimmed and transparent, the animation already sliced from a sheet and assembled
into a looping GIF.

## Why not just call the API

The AI Studio API key is the obvious route and it does not work on a free plan:
every image model answers `429 RESOURCE_EXHAUSTED`, because the free tier grants
zero image quota. Enabling billing fixes it and starts charging per image, while
the Gemini subscription already sitting on the same account goes unused.

NanoBridge takes the other door: it authenticates as the browser does, with the
`__Secure-1PSID` cookie already in Chrome, and spends the subscription's quota.
Nothing to paste, nothing to buy.

| Backend | Auth | Cost |
| --- | --- | --- |
| `web` (default) | Gemini cookies read from the browser | the plan already paid for |
| `api` (fallback) | `GEMINI_API_KEY` | per image, and needs active billing |

`nanobridge doctor` reports which one is live and how much quota is left.

## Install

```bash
gh repo clone NspxMiguel/NanoBridge ~/Projects/NanoBridge
cd ~/Projects/NanoBridge && ./install.sh
```

The installer builds a virtualenv, puts `nanobridge` on `PATH`, registers the MCP
server with Claude Code, and installs the agent skill. Run it again to upgrade;
it never creates a second `nanobridge` on `PATH`.

Requirements: Python 3.11+, and a browser signed in to
<https://gemini.google.com>.

> This repository is private, so `gh` (authenticated) is the way to clone it and
> there is no Homebrew cask: a cask downloads a source tarball over plain HTTPS,
> which a private repository answers with a 404.

## Use it from the shell

```bash
nanobridge doctor                        # backends, quota, config path
nanobridge sprite "a green slime" --style pixel --size 128
nanobridge icon "a compass rose" --style flat
nanobridge gen "a seamless stone wall texture, top-down, tileable"
nanobridge edit hero.png "make the sky stormy, keep everything else"

nanobridge sheet "a green slime" --grid 4x2 \
  --action "squash down and stretch back up, a bouncy idle loop" --fps 10
```

Sheets are generated, sliced into frames, and assembled into a looping GIF with
the transparency preserved — GIF has no alpha channel, so a palette index is
reserved for the empty pixels.

Two commands never touch the network, so they cost no quota and work on images
from anywhere:

```bash
nanobridge cut photo.jpg --transparent --trim --size 256
nanobridge slice sheet.png --grid 6x1 --size 96
```

## Use it from an agent

The MCP server exposes `generate_image`, `generate_sprite`,
`generate_sprite_sheet`, `generate_icon`, `edit_image`, `cut_image`,
`slice_sheet` and `nanobridge_status`.

Every generating tool returns the image **back to the model**, downscaled to a
512px preview, alongside the paths on disk. That is the point: an agent that
cannot see what it drew cannot tell a good sprite from a broken one, and iterates
blind.

Registering it by hand:

```bash
claude mcp add nanobridge --scope user -- /path/to/.venv/bin/nanobridge mcp
```

## What the post-processing does

The model returns a large JPEG on a flat background. Sprites need the opposite,
so the pipeline is part of the tool rather than an afterthought:

- **Background removal is border-connected**, not colour-matched. A white eye
  inside a sprite has the same colour as the white behind it; only the region
  that reaches the image border is erased.
- **Trim** crops to the drawing.
- **Resize is nearest-neighbour.** Pixel art resampled with a smooth filter stops
  looking like pixel art.
- **Slicing is geometric.** The grid asked for in the prompt is the grid used to
  cut, and the individual frames are written out — that is where you see whether
  the model actually obeyed.

## Languages

Screen text is Portuguese and English. The system locale picks the default,
`nanobridge lang pt|en` saves a choice, and `NANOBRIDGE_LANG=pt` overrides both
for one run.

## Limits worth knowing

- The web backend depends on a browser session. When it expires, sign in again at
  <https://gemini.google.com>; `nanobridge doctor` says so explicitly.
- It talks to an interface Google does not document, so a change on their side can
  break it. The `api` backend is the fallback that stays put.
- Generated images carry Google's SynthID watermark.

## License

MIT.
