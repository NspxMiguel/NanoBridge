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

from . import config, core, imaging
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
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate one game sprite: background removed, trimmed, saved as PNG.

    `style` is one of pixel, flat, cartoon, 3d, realistic, sketch — or any free
    text describing the look you want.
    """
    result = await core.sprite(subject, style=style, size=size, **_kwargs(out_dir, name, backend, None))
    return _respond(result)


@mcp.tool()
@handled
async def generate_icon(
    subject: str,
    style: str = "flat",
    size: int | None = 512,
    out_dir: str | None = None,
    name: str | None = None,
    backend: str | None = None,
) -> list[TextContent | ImageContent]:
    """Generate a single app/UI icon on a transparent background.

    Prefer a hand-written SVG for plain interface icons; reach for this when the
    icon wants illustration an SVG would not carry.
    """
    result = await core.icon(subject, style=style, size=size, **_kwargs(out_dir, name, backend, None))
    return _respond(result)


@mcp.tool()
@handled
async def generate_sprite_sheet(
    subject: str,
    action: str = "a simple looping idle animation",
    grid: str = "4x2",
    style: str = "pixel",
    fps: int = 10,
    frame_size: int | None = 128,
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
