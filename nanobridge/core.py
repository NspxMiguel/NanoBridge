"""A camada que junta canal + pós-processamento.

O CLI e o servidor MCP são casca fina em cima daqui; toda regra de verdade
(nome de arquivo, recorte, transparência, corte de folha) mora neste módulo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import imaging
from .backends import Backend, pick
from .config import default_out_dir
from .errors import NoImageError

# Estes moldes existem porque prompt cru rende imagem bonita e sprite inútil:
# sem pedir fundo chapado e enquadramento único, vem cena com sombra e chão.
SPRITE_TEMPLATE = (
    "A single game sprite of {subject}. {style}. "
    "One subject only, centred, full body, facing the camera, no cropping. "
    "Flat solid pure white background (#FFFFFF), no gradient, no shadow, no floor, "
    "no text, no watermark, no border, no frame, no mockup, no extra objects."
)

SHEET_TEMPLATE = (
    "A sprite sheet of {subject}, laid out as an exact {cols}x{rows} grid "
    "({total} frames total, read left to right, top to bottom). {style}. "
    "The frames are a single animation: {action}. "
    "Every frame is the same size, same scale and same centring, evenly spaced. "
    "Flat solid pure white background (#FFFFFF) behind every frame, no grid lines, "
    "no numbering, no captions, no shadow, no border."
)

ICON_TEMPLATE = (
    "A single app icon of {subject}. {style}. "
    "Centred, square composition, flat solid pure white background (#FFFFFF), "
    "no text, no watermark, no rounded-corner mockup, no device frame, no shadow."
)

STYLES = {
    "pixel": "Pixel art, low resolution look, chunky pixels, limited palette, crisp 1px black outline, no anti-aliasing",
    "flat": "Flat vector illustration, bold clean shapes, limited palette, no gradients, no texture",
    "cartoon": "Clean 2D cartoon illustration, bold outlines, cel shading",
    "3d": "Soft 3D render, clay-like material, gentle studio lighting",
    "realistic": "Photorealistic render, sharp focus, neutral studio lighting",
    "sketch": "Black ink line drawing, hand-drawn, no fill",
}
DEFAULT_STYLE = "pixel"


def slugify(text: str, fallback: str = "nanobridge") -> str:
    """Nome de arquivo previsível a partir do prompt — sem acento, sem espaço."""
    normalised = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalised).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:48] or fallback).strip("-") or fallback


def style_text(style: str | None) -> str:
    if not style:
        return STYLES[DEFAULT_STYLE]
    return STYLES.get(style.lower(), style)


@dataclass
class Generated:
    """Resultado pronto para mostrar: onde ficou cada arquivo e como voltar nele."""

    paths: list[Path] = field(default_factory=list)
    frames: list[Path] = field(default_factory=list)
    gif: Path | None = None
    text: str = ""
    backend: str = ""
    model: str = ""
    conversation: str | None = None
    prompt: str = ""
    grid: tuple[int, int] | None = None


async def _run(
    prompt: str,
    *,
    backend: Backend | None = None,
    backend_name: str | None = None,
    files: list[str | Path] | None = None,
    model: str | None = None,
    conversation: str | None = None,
    out_dir: Path | None = None,
    name: str | None = None,
    transparent: bool = False,
    trim: bool = False,
    size: int | None = None,
    tolerance: int = 24,
) -> Generated:
    chosen = backend or pick(backend_name)
    result = await chosen.generate(prompt, files=files, model=model, conversation=conversation)
    if not result.images:
        raise NoImageError(result.text)

    target = Path(out_dir or default_out_dir()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    stem = name or f"{slugify(prompt)}-{datetime.now().strftime('%H%M%S')}"

    paths: list[Path] = []
    for index, raw in enumerate(result.images):
        suffix = "" if len(result.images) == 1 else f"-{index + 1}"
        needs_pillow = transparent or trim or size
        if needs_pillow:
            img = imaging.open_image(raw)
            if transparent:
                img = imaging.make_transparent(img, tol=tolerance)
            if trim:
                img = imaging.trim(img, tol=tolerance)
            if size:
                img = imaging.fit(img, size, pad=False)
            path = target / f"{stem}{suffix}.png"
            img.save(path)
        else:
            path = target / f"{stem}{suffix}{imaging.sniff_extension(raw)}"
            path.write_bytes(raw)
        paths.append(path)

    return Generated(
        paths=paths,
        text=result.text,
        backend=result.backend,
        model=result.model,
        conversation=result.conversation,
        prompt=prompt,
    )


async def generate(prompt: str, **kwargs) -> Generated:
    """Imagem livre: o prompt vai como o usuário escreveu."""
    return await _run(prompt, **kwargs)


async def sprite(subject: str, *, style: str | None = None, **kwargs) -> Generated:
    """Sprite solto — já sai recortado e transparente, que é como se usa."""
    kwargs.setdefault("transparent", True)
    kwargs.setdefault("trim", True)
    prompt = SPRITE_TEMPLATE.format(subject=subject, style=style_text(style))
    kwargs.setdefault("name", slugify(subject))
    return await _run(prompt, **kwargs)


async def icon(subject: str, *, style: str | None = None, **kwargs) -> Generated:
    kwargs.setdefault("transparent", True)
    kwargs.setdefault("trim", True)
    kwargs.setdefault("name", f"icon-{slugify(subject)}")
    prompt = ICON_TEMPLATE.format(subject=subject, style=style_text(style or "flat"))
    return await _run(prompt, **kwargs)


async def edit(image: str | Path, prompt: str, **kwargs) -> Generated:
    """Edita uma imagem que já existe — a mesma conversa aceita várias rodadas."""
    kwargs.setdefault("name", f"{Path(image).stem}-edit")
    return await _run(prompt, files=[image], **kwargs)


async def sheet(
    subject: str,
    *,
    grid: str = "4x2",
    action: str = "a simple looping idle animation",
    style: str | None = None,
    fps: int = 10,
    frame_size: int | None = None,
    gif: bool = True,
    **kwargs,
) -> Generated:
    """Folha de sprites: gera a grade, corta em quadros e monta o GIF.

    O corte é geométrico, não adivinhado: a grade pedida no prompt é a mesma
    usada para fatiar. Quando o modelo desobedece a grade, o jeito de descobrir
    é olhar os quadros — por isso eles são salvos, não só o GIF.
    """
    cols, rows = imaging.parse_grid(grid)
    prompt = SHEET_TEMPLATE.format(
        subject=subject,
        style=style_text(style),
        cols=cols,
        rows=rows,
        total=cols * rows,
        action=action,
    )
    stem = kwargs.pop("name", None) or f"sheet-{slugify(subject)}"
    transparent = kwargs.pop("transparent", True)
    tolerance = kwargs.get("tolerance", 24)
    generated = await _run(prompt, name=stem, transparent=False, trim=False, **kwargs)

    source = generated.paths[0]
    full = imaging.open_image(source)
    if transparent:
        full = imaging.make_transparent(full, tol=tolerance)
        # A folha crua costuma vir em JPEG, que não guarda alfa: a versão
        # transparente tem que virar PNG, e a original sai de cena.
        transparent_path = source.with_suffix(".png")
        full.save(transparent_path)
        if transparent_path != source:
            source.unlink(missing_ok=True)
        source = transparent_path
        generated.paths = [source] + generated.paths[1:]

    frames_dir = source.parent / f"{stem}-frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    frames = imaging.slice_sheet(full, cols, rows)
    for index, frame in enumerate(frames, start=1):
        if frame_size:
            frame = imaging.fit(frame, frame_size)
        path = frames_dir / f"{stem}-{index:02d}.png"
        frame.save(path)
        frame_paths.append(path)

    generated.frames = frame_paths
    generated.grid = (cols, rows)
    if gif and frame_paths:
        generated.gif = imaging.save_gif(
            [imaging.open_image(p) for p in frame_paths], source.parent / f"{stem}.gif", fps=fps
        )
    return generated
