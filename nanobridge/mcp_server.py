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


def _respond_mesh(result: core.Mesh3D, previews: int = 4) -> list[TextContent | ImageContent]:
    """Resposta das ferramentas 3D. Mesmo contrato das 2D: JSON puro no texto.

    A malha em si não vira pré-visualização — GLB não é imagem, e mandar bytes
    de malha para o agente só queima contexto. Quem mostra o resultado são os
    quadros renderizados, que é justamente o ponto de existir um render aqui.
    """
    resumo = {
        "mesh": str(result.path),
        "engine": result.engine,
        "engine_label": result.engine_label,
        "license": result.license,
        "reference_image": str(result.source_image) if result.source_image else None,
        "frames": [str(p) for p in result.frames],
        "sheet": str(result.sheet) if result.sheet else None,
        "gif": str(result.gif) if result.gif else None,
        "stats": result.stats,
    }
    if result.stats.get("depth_ratio", 1.0) < 0.10:
        resumo["warning"] = t("mesh3d.flat_warning")
    saida: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(resumo, ensure_ascii=False))
    ]
    for caminho in (result.sheet, *result.frames[:previews]):
        if caminho:
            saida.append(_preview(caminho))
    return saida


@mcp.tool()
@handled
def list_mesh_engines() -> str:
    """The 3D engines NanoBridge can call, and what each one gives back.

    Nano Banana draws pixels; it never returns geometry. These engines are the
    other half: single-image-to-3D models that turn one clean reference picture
    into a closed mesh. They are free public Hugging Face Spaces — no key, no
    account — so the cost is queueing, not money.
    """
    from . import mesh3d

    return json.dumps(
        [
            {
                "name": e.name,
                "label": e.label,
                "space": e.space,
                "license": e.license,
                "vertex_colors": e.colored,
                "front_yaw": e.front_yaw,
            }
            for e in mesh3d.ENGINES
        ],
        ensure_ascii=False,
    )


@mcp.tool()
@handled
def generate_mesh(
    image: str,
    out_dir: str | None = None,
    name: str | None = None,
    engine: str | None = None,
) -> list[TextContent | ImageContent]:
    """Turn ONE image into a real 3D mesh (.glb) with a single-image-to-3D model.

    The input picture decides everything. It must show one object, whole, facing
    the camera, on a plain background, with visible shading — a 3D render, a
    photo, or a painted character sheet. Flat pixel art does NOT work: there is
    no volume in it to reconstruct, and the result comes back as a slab (watch
    `stats.depth_ratio`, which is under 0.1 when that happens).

    To go from a text prompt in one step, use `generate_sprite_3d` instead.
    """
    resultado = core.mesh_from_image(
        image, out_dir=Path(out_dir) if out_dir else None, name=name, engine=engine
    )
    return _respond_mesh(resultado, previews=0)


@mcp.tool()
@handled
def render_turntable(
    mesh: str,
    out_dir: str | None = None,
    name: str | None = None,
    frames: int = 8,
    size: int = 192,
    pitch: float = 15.0,
    start: float | None = None,
    zoom: float = 0.92,
    engine: str | None = None,
    gif: bool = False,
    fps: int = 12,
    pixels: int | None = None,
    palette: str | None = None,
) -> list[TextContent | ImageContent]:
    """Render a .glb/.obj mesh as an N-direction sprite — the classic pre-rendered look.

    This is what makes the 3D useful in a 2D game: eight frames, 45 degrees
    apart, all framed at the same scale so the character does not grow and
    shrink as it turns. `pitch` tilts the camera — 0 is a side-on platformer
    view, 30 is proper isometric.

    Everything is drawn locally with a software rasteriser: no GPU, no network,
    deterministic output. The frames come out as ordinary PNGs, so `pack_atlas`,
    `apply_palette` and `slice_sheet` all work on them afterwards.
    """
    resultado = core.render_turntable(
        mesh, out_dir=Path(out_dir) if out_dir else None, name=name, frames=frames,
        size=size, pitch=pitch, start=start, zoom=zoom, engine=engine, gif=gif,
        fps=fps, pixels=pixels, palette=palette,
    )
    return _respond_mesh(resultado)


@mcp.tool()
@handled
async def generate_sprite_3d(
    subject: str,
    out_dir: str | None = None,
    name: str | None = None,
    engine: str | None = None,
    frames: int = 8,
    size: int = 192,
    pitch: float = 15.0,
    zoom: float = 0.92,
    gif: bool = False,
    fps: int = 12,
    pixels: int | None = None,
    palette: str | None = None,
    reference: str | None = None,
) -> list[TextContent | ImageContent]:
    """Prompt to 3D mesh to an 8-direction sprite sheet, in one call.

    Three models in a row, and each step has its own tool if you need to redo
    just that one: Nano Banana draws a clean 3D-render reference, a
    single-image-to-3D model reconstructs geometry from it, and a local
    rasteriser spins that geometry into game-ready frames.

    Describe the character as a physical object, not as art: "a round brown
    mushroom enemy with big angry eyes" works, "pixel art mushroom" does not —
    the reconstruction needs volume and shading to read. Pass `reference` to
    reuse a picture you already have and skip the drawing step.
    """
    resultado = await core.sprite_3d(
        subject, out_dir=Path(out_dir) if out_dir else None, name=name, engine=engine,
        frames=frames, size=size, pitch=pitch, zoom=zoom, gif=gif, fps=fps,
        pixels=pixels, palette=palette, reference=reference,
    )
    return _respond_mesh(resultado)


def _respond_refined(result: core.Refined, renders=None) -> list[TextContent | ImageContent]:
    resumo = {
        "outputs": [str(p) for p in result.outputs],
        "texture": str(result.texture) if result.texture else None,
        "before": result.before,
        "after": result.after,
        "retopo": result.retopo,
        "uv_created": result.uv_created,
        "renders": [str(p) for p in (renders or [])],
    }
    if result.texture is None:
        resumo["warning"] = t("refine.no_color")
    saida: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(resumo, ensure_ascii=False))
    ]
    for caminho in (renders or [])[:4]:
        saida.append(_preview(caminho))
    return saida


@mcp.tool()
@handled
def blender_status() -> str:
    """Whether Blender is reachable, and where. Refining and rendering need it.

    Blender is an external dependency on purpose: it is a 400MB download, and
    nobody who only wants 2D sprites should be made to install it. Install with
    `brew install --cask blender`, or point NANOBRIDGE_BLENDER at the binary.
    """
    from . import blender

    return json.dumps({"found": blender.find_blender(), "version": blender.version()},
                      ensure_ascii=False)


@mcp.tool()
@handled
def refine_mesh(
    mesh: str,
    out_dir: str | None = None,
    name: str | None = None,
    faces: str = "game",
    retopo: bool = True,
    texture_size: int = 1024,
    formats: list[str] | None = None,
) -> list[TextContent | ImageContent]:
    """Turn a raw AI mesh into an actual asset, in Blender. Needs Blender installed.

    What a 3D generator returns is not an asset: a shell of hundreds of thousands
    of irregular triangles, no UVs, colour stored per vertex — which only its own
    viewer understands. Open that in Blender and you get a grey blob; drop it in
    a game engine and it has no texture.

    This does what an artist would, in the same order: weld, retopologise into
    **quads** with QuadriFlow, UV unwrap, and bake the dense mesh's colour onto
    the clean topology — the same high-to-low transfer used between a sculpt and
    a game model. Then it exports .glb / .fbx / .obj / .usdz / .blend.

    `faces` takes "game" (6k), "detail" (20k), "high" (60k) or a number as a
    string. Check `after.quad_ratio` in the result: 1.0 means the retopology
    landed; anything lower means it fell back to decimation, and the mesh is
    still triangles.
    """
    resultado = core.refine_mesh(
        mesh, out_dir=Path(out_dir) if out_dir else None, name=name, faces=faces,
        retopo=retopo, texture_size=texture_size, formats=formats or [".glb"],
    )
    return _respond_refined(resultado)


@mcp.tool()
@handled
def render_mesh(
    mesh: str,
    out_dir: str | None = None,
    name: str | None = None,
    frames: int = 1,
    size: int = 640,
    pitch: float = 15.0,
    engine: str = "eevee",
    samples: int = 64,
    transparent: bool = True,
    mesh_engine: str | None = None,
) -> list[TextContent | ImageContent]:
    """Render a mesh properly, in Blender: studio lighting, real materials, shadows.

    Different from `render_turntable`, which rasterises points here in NumPy.
    That one is for small sprites and runs anywhere. This one shows the model as
    it is — cast shadow, occlusion, engine antialiasing — and is the image that
    goes in a README, or the proof that the mesh survives a close look.

    `engine` is "eevee" (seconds) or "cycles" (minutes, and better).
    """
    caminhos = core.render_mesh(
        mesh, out_dir=Path(out_dir) if out_dir else None, name=name, frames=frames,
        size=size, pitch=pitch, engine=engine, samples=samples, transparent=transparent,
        mesh_engine=mesh_engine,
    )
    resumo = {"frames": [str(p) for p in caminhos]}
    saida: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(resumo, ensure_ascii=False))
    ]
    for caminho in caminhos[:4]:
        saida.append(_preview(caminho))
    return saida


@mcp.tool()
@handled
async def generate_model_3d(
    subject: str,
    out_dir: str | None = None,
    name: str | None = None,
    kind: str = "auto",
    engine: str | None = None,
    faces: str = "game",
    texture_size: int = 1024,
    formats: list[str] | None = None,
    render_frames: int = 4,
    render_size: int = 640,
    render_engine: str = "eevee",
    reference: str | None = None,
) -> list[TextContent | ImageContent]:
    """Prompt to a Blender-ready 3D asset, in one call. The flagship 3D tool.

    Four models and programs in a row: Nano Banana draws a clean reference, a
    single-image-to-3D model reconstructs geometry, Blender retopologises it into
    quads with UVs and a baked texture, and Blender renders a preview. Each step
    has its own tool, because each fails for a different reason.

    **Set `kind`.** "character" asks for an A-pose and a full body; "prop" asks
    for a three-quarter view with no face and no limbs. It matters: asking for a
    body when the subject is an object gets you one — a treasure chest came back
    with arms and legs on the first measured run.

    Describe the physical thing, not the art: "a wooden treasure chest with iron
    bands and a heavy padlock" works, "3D model of a chest asset" does not.
    Needs Blender — check `blender_status` first.
    """
    resultado = await core.model_3d(
        subject, out_dir=Path(out_dir) if out_dir else None, name=name, kind=kind,
        engine=engine, faces=faces, texture_size=texture_size,
        formats=formats or [".glb", ".fbx", ".blend"], render_frames=render_frames,
        render_size=render_size, render_engine=render_engine, reference=reference,
    )
    saida = _respond_refined(resultado.refined, resultado.renders) if resultado.refined else []
    if saida:
        dados = json.loads(saida[0].text)
        dados.update(reference=str(resultado.reference) if resultado.reference else None,
                     raw_mesh=str(resultado.raw_mesh) if resultado.raw_mesh else None,
                     engine=resultado.engine, engine_label=resultado.engine_label,
                     license=resultado.license)
        saida[0] = TextContent(type="text", text=json.dumps(dados, ensure_ascii=False))
    return saida


def run() -> None:
    config.apply_saved_language()
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    run()
