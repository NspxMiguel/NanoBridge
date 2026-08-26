"""Servidor MCP: é isto que dá ao agente acesso direto ao Nano Banana.

As ferramentas devolvem a imagem *de volta* para o modelo, não só o caminho no
disco. Isso é o ponto: sem ver o que saiu, o agente não sabe se o sprite ficou
bom nem o que corrigir na próxima rodada.
"""

from __future__ import annotations

import base64
import functools
import inspect
import json
from pathlib import Path

try:  # mcp >= 2.0
    from mcp.server import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover - mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent

from . import config, core, imaging, palettes
from .backends import all_backends, pick
from .core import STYLES
from .errors import NanoBridgeError
from .i18n import t

mcp = _Server("nanobridge")

# Imagem grande demais estoura a janela de contexto do agente sem ajudar em
# nada: para julgar um sprite, uma pré-visualização pequena basta.
PREVIEW_MAX_SIDE = 512


def handled(fn):
    """Transforma falha prevista em mensagem, não em traceback.

    O servidor MCP trata qualquer exceção que não seja `ToolError` como queda:
    o agente recebe "Error executing tool X" e um traceback no log, e perde a
    única frase que diria o que fazer — renovar a sessão do Gemini, corrigir o
    caminho, trocar a grade. Erro imprevisto continua subindo cru, que é o certo:
    bug tem que ser barulhento.
    """

    @functools.wraps(fn)
    async def async_wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (NanoBridgeError, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (NanoBridgeError, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper




def _preview(path: Path) -> ImageContent:
    img = imaging.open_image(path)
    if max(img.size) > PREVIEW_MAX_SIDE:
        ratio = PREVIEW_MAX_SIDE / max(img.size)
        img = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))))
    import io

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return ImageContent(
        type="image",
        data=base64.b64encode(buffer.getvalue()).decode(),
        mimeType="image/png",
    )


def _respond(result: core.Generated) -> list[TextContent | ImageContent]:
    """Uma resposta, um formato: o bloco de texto é sempre JSON puro.

    Prefixar uma linha solta antes do JSON obrigava quem lê a saber de antemão
    qual ferramenta respondeu; o que era nota virou campo.
    """
    summary = {
        "paths": [str(p) for p in result.paths],
        "frames": [str(p) for p in result.frames],
        "gif": str(result.gif) if result.gif else None,
        "backend": result.backend,
        "conversation": result.conversation,
    }
    if result.grid:
        summary["grid"] = f"{result.grid[0]}x{result.grid[1]}"
    out: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(summary, ensure_ascii=False))
    ]
    for path in result.paths:
        out.append(_preview(path))
    # Numa folha, os quadros isolados é que revelam se o modelo respeitou a grade.
    for path in result.frames[:8]:
        out.append(_preview(path))
    return out


def _kwargs(out_dir: str | None, name: str | None, backend: str | None, model: str | None) -> dict:
    kwargs: dict = {}
    if out_dir:
        kwargs["out_dir"] = Path(out_dir).expanduser()
    if name:
        kwargs["name"] = name
    if backend:
        kwargs["backend_name"] = backend
    if model:
        kwargs["model"] = model
    return kwargs


@mcp.tool()
@handled
async def generate_image(
    prompt: str,
    out_dir: str | None = None,
    name: str | None = None,
    transparent: bool = False,
    trim: bool = False,
    size: int | None = None,
    palette: str | None = None,
    reference_images: list[str] | None = None,
    conversation: str | None = None,
    backend: str | None = None,
    model: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate an image with Nano Banana (Gemini) and return it for inspection.

    Free-form: the prompt is sent as written. Use `reference_images` to give the
    model something to work from, and pass back the returned `conversation` to
    keep editing the same image across calls.
    """
    result = await core.generate(
        prompt,
        files=reference_images,
        transparent=transparent,
        trim=trim,
        size=size,
        palette=palette,
        conversation=conversation,
        **_kwargs(out_dir, name, backend, model),
    )
    return _respond(result)


@mcp.tool()
@handled
async def generate_sprite(
    subject: str,
    style: str = "pixel",
    size: int | None = 256,
    palette: str | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate one game sprite: background removed, trimmed, saved as PNG.

    `style` is one of pixel, flat, cartoon, 3d, realistic, sketch — or any free
    text describing the look you want.

    `palette` locks the output to a fixed set of colours — a built-in name (see
    `list_palettes`), a .hex file, or a comma-separated #RRGGBB list. Pass the
    same palette to every sprite in a cast and they look like one game; without
    it the model picks slightly different greens each time. `extract_palette`
    turns a sprite you already like into that palette.
    """
    result = await core.sprite(
        subject, style=style, size=size, palette=palette, **_kwargs(out_dir, name, backend, None)
    )
    return _respond(result)


@mcp.tool()
@handled
async def generate_icon(
    subject: str,
    style: str = "flat",
    size: int | None = 512,
    palette: str | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate a single app/UI icon on a transparent background.

    Prefer a hand-written SVG for plain interface icons; reach for this when the
    icon wants illustration an SVG would not carry.
    """
    result = await core.icon(
        subject, style=style, size=size, palette=palette, **_kwargs(out_dir, name, backend, None)
    )
    return _respond(result)


@mcp.tool()
@handled
async def generate_cast(
    subjects: list[str],
    style: str = "pixel",
    size: int | None = 128,
    palette: str = "auto",
    pixels: int | None = None,
    zoom: int = 1,
    atlas: bool = True,
    formats: list[str] | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate several sprites that belong to the same game, and pack them.

    This is the one to reach for when the task is 'a set of characters' rather
    than a single image. Generating them one at a time gives a cast that does
    not match — the model picks a slightly different green each time.

    `palette="auto"` (the default) generates the first subject freely, reads its
    palette, and locks every other subject to it, so the set is coherent without
    anyone choosing a palette. Pass a built-in name, a .hex path or a #RRGGBB
    list to choose one instead.

    The rest are generated concurrently, so a cast of six does not cost six
    times one. A subject that fails does not lose the others — it comes back in
    `failed` with the reason, and the cast returns with whoever made it.
    """
    result = await core.cast(
        subjects,
        style=style,
        size=size,
        palette=palette,
        atlas=atlas,
        formats=formats,
        atlas_name=name,
        pixels=pixels,
        zoom=zoom,
        out_dir=Path(out_dir).expanduser() if out_dir else None,
        backend_name=backend,
    )
    summary = {
        "sprites": [str(s.paths[0]) for s in result.sprites],
        "palette": [palettes.rgb_to_hex(c) for c in result.palette],
        "atlas": str(result.atlas.path) if result.atlas else None,
        "manifests": ({k: str(v) for k, v in result.atlas.manifests.items()} if result.atlas else {}),
        "failed": result.failed,
    }
    out: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(summary, ensure_ascii=False))
    ]
    # O atlas mostra o elenco inteiro de uma vez; sem ele, os sprites um a um.
    if result.atlas:
        out.append(_preview(result.atlas.path))
    else:
        for generated in result.sprites[:8]:
            out.append(_preview(generated.paths[0]))
    return out


@mcp.tool()
@handled
async def generate_sprite_sheet(
    subject: str,
    action: str = "a simple looping idle animation",
    grid: str = "4x2",
    style: str = "pixel",
    fps: int = 10,
    frame_size: int | None = 128,
    palette: str | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate an animation sheet, slice it into frames and assemble a GIF.

    The slice is geometric — the grid asked for in the prompt is the grid used to
    cut. Look at the returned frames: if the model ignored the grid, the frames
    are where you see it, and a different `grid` or `action` is the fix.
    """
    result = await core.sheet(
        subject,
        grid=grid,
        action=action,
        style=style,
        fps=fps,
        frame_size=frame_size,
        palette=palette,
        **_kwargs(out_dir, name, backend, None),
    )
    return _respond(result)


@mcp.tool()
@handled
async def generate_variations(
    subject: str,
    count: int = 4,
    style: str = "pixel",
    size: int | None = 160,
    palette: str | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate several takes on the same subject and return them to compare.

    Asking for one image and hoping is the expensive loop: when it is wrong, the
    whole request is made again. This produces several at once, in parallel,
    each pushed in a different direction — repeating an identical prompt gives
    timid variations because the model converges on the same drawing.

    The contact sheet comes back as one image so you can look at all the options
    together and pick, instead of requesting them one at a time.
    """
    result = await core.variations(
        subject,
        count,
        style=style,
        size=size,
        palette=palette,
        **_kwargs(out_dir, name, backend, None),
    )
    summary = {
        "paths": [str(p) for p in result.paths],
        "contact_sheet": str(result.contact_sheet) if result.contact_sheet else None,
        "failed": result.failed,
    }
    out: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(summary, ensure_ascii=False))
    ]
    # A folha inteira numa imagem: é assim que se compara.
    if result.contact_sheet:
        out.append(_preview(result.contact_sheet))
    else:
        for path in result.paths[:6]:
            out.append(_preview(path))
    return out


@mcp.tool()
@handled
async def generate_texture(
    subject: str,
    style: str = "realistic",
    repair: bool = True,
    preview: bool = False,
    palette: str | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate a tileable texture and *prove* it tiles.

    Models say "seamless" and often are not — the seam only shows up once four
    copies sit side by side in the game. This measures the seam against the
    texture's own internal variation, stitches the image if it fails, and
    returns both numbers so the claim is checkable rather than taken on trust.

    `preview=True` also writes a 3x3 tiling, because a threshold convinces
    nobody on its own.
    """
    result = await core.texture(
        subject,
        style=style,
        repair=repair,
        preview=preview,
        palette=palette,
        **_kwargs(out_dir, name, backend, None),
    )
    summary = {
        "path": str(result.path),
        "seam": {k: round(v, 3) for k, v in result.seam.items()},
        "seam_before": {k: round(v, 3) for k, v in result.seam_before.items()},
        "repaired": result.repaired,
        "threshold": core.SEAM_THRESHOLD,
        "preview": str(result.preview) if result.preview else None,
    }
    out: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(summary, ensure_ascii=False))
    ]
    out.append(_preview(result.preview or result.path))
    return out


@mcp.tool()
@handled
def build_normal_map(
    image: str, out: str | None = None, strength: float = 2.0, blur: float = 1.0
) -> list[TextContent | ImageContent]:
    """Derive a normal map from a sprite, for 2D dynamic lighting. Local, no quota.

    Godot, Phaser and Unity 2D take a normal map alongside the sprite to light
    it. Drawing one by hand is work and the model does not produce them
    reliably, but it can be derived: where luminance rises steeply there is a
    slope, and its direction is the normal.

    It is not physically correct — luminance conflates 'bright' with 'high', so
    a flat bright patch reads as raised. For a lit 2D sprite that is fine and is
    what most tools do; for a real scanned surface it is not.
    """
    target = core.build_normal_map(
        image, out=Path(out).expanduser() if out else None, strength=strength, blur=blur
    )
    return [TextContent(type="text", text=json.dumps({"path": str(target)})), _preview(target)]


@mcp.tool()
@handled
def check_tileable(image: str, preview: bool = False, times: int = 3) -> str:
    """Measure how badly an image jumps when repeated. Local, no quota.

    Returns the seam on each axis as a ratio against the image's own internal
    variation, so a noisy texture is not judged by the standard of a flat wall.
    Under `SEAM_THRESHOLD` nobody sees it.
    """
    seam = core.check_tileable(image)
    body = {
        "seam": {k: round(v, 3) for k, v in seam.items()},
        "threshold": core.SEAM_THRESHOLD,
        "tiles_cleanly": max(seam.values()) <= core.SEAM_THRESHOLD,
    }
    if preview:
        body["preview"] = str(core.tile_preview(image, times=times))
    return json.dumps(body, ensure_ascii=False)


@mcp.tool()
@handled
def repair_tileable(
    image: str, out: str | None = None, blend: float = 0.12
) -> list[TextContent | ImageContent]:
    """Stitch an existing image so it repeats without a visible seam. Local, no quota."""
    before = core.check_tileable(image)
    target = core.repair_tileable(image, out=Path(out).expanduser() if out else None, blend=blend)
    after = core.check_tileable(target)
    return [
        TextContent(type="text", text=json.dumps({
            "path": str(target),
            "seam_before": {k: round(v, 3) for k, v in before.items()},
            "seam": {k: round(v, 3) for k, v in after.items()},
        }, ensure_ascii=False)),
        _preview(target),
    ]


@mcp.tool()
@handled
async def animate_sprite(
    image: str,
    action: str = "a simple looping idle animation",
    grid: str = "4x1",
    fps: int = 10,
    frame_size: int | None = 128,
    palette: str | None = None,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Animate a sprite that already exists, keeping that exact character.

    This is the difference between "make an animation of a knight" and "animate
    THIS knight". `generate_sprite_sheet` does the first: it draws a new
    character from the text, so the animation is not the sprite you already
    approved. Here the image goes along as a reference and the text only
    describes the movement.

    Reach for this whenever the animation should be of something already
    generated — a cast member, an edited sprite, art from anywhere on disk.
    """
    result = await core.animate(
        image,
        action,
        grid=grid,
        fps=fps,
        frame_size=frame_size,
        palette=palette,
        **_kwargs(out_dir, name, backend, None),
    )
    return _respond(result)


@mcp.tool()
@handled
async def edit_image(
    image: str,
    prompt: str,
    out_dir: str | None = None,
    name: str | None = None,
    transparent: bool = False,
    trim: bool = False,
    size: int | None = None,
    conversation: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Edit an existing image file with a natural-language instruction.

    Works on any image on disk, not only ones this server made — recolour, remove
    a background object, change a pose, restyle.
    """
    result = await core.edit(
        image,
        prompt,
        transparent=transparent,
        trim=trim,
        size=size,
        conversation=conversation,
        **_kwargs(out_dir, name, backend, None),
    )
    return _respond(result)


@mcp.tool()
@handled
def list_atlas_formats() -> str:
    """The manifest formats `pack_atlas` can write, and what reads each one."""
    return json.dumps(
        {
            "nanobridge": "this project's own shape: a flat list of named rectangles",
            "phaser": "TexturePacker JSON hash — Phaser, PixiJS, Cocos",
            "texturepacker": "same as phaser, under the tool's name",
            "godot": "a .tres resource with one AtlasTexture per sprite",
            "css": "one CSS class per sprite, with background-position",
            "aseprite": "Aseprite's JSON array shape",
        },
        indent=2,
    )


@mcp.tool()
@handled
def list_palettes() -> str:
    """The built-in palettes available to `palette` arguments, with their colours."""
    lines = []
    for name in palettes.names():
        colours = palettes.resolve(name)
        lines.append(f"{name} ({len(colours)}): " + " ".join(palettes.rgb_to_hex(c) for c in colours))
    lines.append(
        "Any `palette` argument also accepts a path to a .hex file (one #RRGGBB per line) "
        "or a comma-separated list of #RRGGBB colours."
    )
    return "\n".join(lines)


@mcp.tool()
@handled
def extract_palette(image: str, count: int = 16, out: str | None = None) -> str:
    """Read the dominant, visually distinct colours out of an existing image.

    This is half of keeping a cast coherent: extract the palette from the first
    sprite you are happy with, then pass it as `palette` to every later
    generation so the whole cast looks like it came from one game rather than
    from six separate sessions.

    Transparent pixels are excluded, and colours too close to each other to tell
    apart are dropped — otherwise a sprite with a large dark area returns four
    near-identical blacks instead of the colours that define the character.
    """
    colours = core.palette_from_image(image, count=count)
    as_hex = [palettes.rgb_to_hex(c) for c in colours]
    saved = palettes.save(colours, Path(out).expanduser()) if out else None
    return json.dumps(
        {"colours": as_hex, "count": len(as_hex), "saved_to": str(saved) if saved else None},
        ensure_ascii=False,
    )


@mcp.tool()
@handled
def apply_palette(
    image: str,
    palette: str,
    out: str | None = None,
    dither: bool = False,
) -> list[TextContent | ImageContent]:
    """Rewrite an image using only a palette's colours. Local, no quota.

    `palette` is a built-in name (see `list_palettes`), a path to a .hex file,
    or a comma-separated list of #RRGGBB. Dithering is off by default: pixel art
    wants flat colour, and error diffusion sprays exactly the half-tone noise
    that locking a palette is meant to remove.
    """
    target = core.apply_palette(image, palette, out=Path(out).expanduser() if out else None, dither=dither)
    return [TextContent(type="text", text=json.dumps({"path": str(target)})), _preview(target)]


@mcp.tool()
@handled
def cut_image(
    image: str,
    out: str | None = None,
    transparent: bool = True,
    trim: bool = True,
    size: int | None = None,
    tolerance: int = 24,
) -> list[TextContent | ImageContent]:
    """Post-process an image locally: drop the flat background, trim, resize.

    No network and no quota — use it on an image that came from anywhere.
    """
    source = core.existing_path(image)
    img = imaging.open_image(source)
    if transparent:
        img = imaging.make_transparent(img, tol=tolerance)
    if trim:
        img = imaging.trim(img, tol=tolerance)
    if size:
        img = imaging.fit(img, size, pad=False)
    target = Path(out) if out else Path(image).with_name(f"{Path(image).stem}-cut.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target)
    return [TextContent(type="text", text=json.dumps({"path": str(target)})), _preview(target)]


@mcp.tool()
@handled
def slice_sheet(
    image: str,
    grid: str = "4x2",
    out_dir: str | None = None,
    frame_size: int | None = None,
    fps: int = 10,
    transparent: bool = True,
    gif: bool = True,
) -> list[TextContent | ImageContent]:
    """Slice an existing sheet into frames and optionally build a GIF. Local only."""
    source = core.existing_path(image)
    cols, rows = imaging.parse_grid(grid)
    img = imaging.open_image(source)
    if transparent:
        img = imaging.make_transparent(img)
    target = Path(out_dir).expanduser() if out_dir else Path(image).with_suffix("")
    target.mkdir(parents=True, exist_ok=True)
    stem = Path(image).stem
    paths = []
    for index, frame in enumerate(imaging.slice_sheet(img, cols, rows), start=1):
        if frame_size:
            frame = imaging.fit(frame, frame_size)
        path = target / f"{stem}-{index:02d}.png"
        frame.save(path)
        paths.append(path)
    gif_path = None
    if gif and paths:
        gif_path = imaging.save_gif([imaging.open_image(p) for p in paths], target / f"{stem}.gif", fps=fps)
    out: list[TextContent | ImageContent] = [
        TextContent(
            type="text",
            text=json.dumps(
                {"frames": [str(p) for p in paths], "gif": str(gif_path) if gif_path else None},
                ensure_ascii=False,
            ),
        )
    ]
    for path in paths[:8]:
        out.append(_preview(path))
    return out


@mcp.tool()
@handled
def pack_atlas(
    images: list[str],
    out_dir: str | None = None,
    name: str | None = None,
    padding: int = 2,
    max_width: int = 2048,
    formats: list[str] | None = None,
) -> list[TextContent | ImageContent]:
    """Pack loose sprite PNGs into one atlas image plus a JSON manifest.

    Neither a `generate_sprite` output nor a `generate_sprite_sheet` output is
    what a game engine wants for a cast of different sprites: it wants one
    sheet and a manifest of where each named sprite sits. This is that —
    local, no quota, works on images from anywhere. `sprites` in the manifest
    keeps the input order; each entry's `name` is the source filename without
    its extension.

    `formats` writes the manifest for real engines instead of only this
    project's own shape — any of: nanobridge, phaser, texturepacker, godot,
    css, aseprite. Ask for several and each gets its own file.
    """
    result = core.build_atlas(
        images,
        out_dir=out_dir,
        name=name,
        padding=padding,
        max_width=max_width,
        formats=formats,
    )
    summary = {
        "path": str(result.path),
        "manifest": str(result.manifest_path),
        "manifests": {k: str(v) for k, v in result.manifests.items()},
        "sprites": [{"name": e.name, "x": e.x, "y": e.y, "w": e.w, "h": e.h} for e in result.entries],
    }
    return [
        TextContent(type="text", text=json.dumps(summary, ensure_ascii=False)),
        _preview(result.path),
    ]


@mcp.tool()
@handled
async def nanobridge_status() -> str:
    """Which backend is live, and how much quota the account has left."""
    lines = []
    for backend in all_backends():
        state = "ready" if backend.available() else "unavailable"
        lines.append(f"{backend.name}: {state} — {backend.status()}")
    try:
        chosen = pick()
        lines.append(f"chosen: {chosen.name}")
        if hasattr(chosen, "quota"):
            for label, value in (await chosen.quota()).items():
                lines.append(f"quota {label}: {value}")
    except NanoBridgeError as exc:
        lines.append(str(exc))
    lines.append(f"styles: {', '.join(STYLES)}")
    lines.append(f"default out dir: {config.default_out_dir()}")
    return "\n".join(lines)


@mcp.tool()
@handled
async def nanobridge_reset() -> str:
    """Drop the cached Gemini web session.

    Call this right after signing back in to gemini.google.com in the browser.
    The web session is otherwise cached for the whole life of this server —
    which can be days — so without an explicit reset, a fresh sign-in only
    takes effect after the next generation fails and reports an expired
    session.
    """
    from .backends.web import WebBackend

    dropped = await WebBackend().reset()
    return t("reset.done") if dropped else t("reset.nothing")


def run() -> None:
    config.apply_saved_language()
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    run()
