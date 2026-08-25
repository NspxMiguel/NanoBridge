"""Pós-processamento: é o que transforma um JPEG de 2816x1536 em sprite usável.

O Nano Banana devolve uma imagem grande, em JPEG, com fundo chapado. Sprite
precisa do contrário: pequeno, PNG, fundo transparente, e às vezes cortado em
quadros. Tudo isso mora aqui, longe de qualquer coisa de rede.
"""

from __future__ import annotations

import io
from collections import deque
from pathlib import Path

from PIL import Image

# Um sprite raramente passa disso; acima daqui o flood fill fica caro à toa.
_MASK_MAX_SIDE = 512


def sniff_extension(data: bytes) -> str:
    """A extensão de verdade do que veio — o Gemini entrega JPEG chamando de PNG."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".bin"


def open_image(data: bytes | str | Path) -> Image.Image:
    if isinstance(data, (str, Path)):
        return Image.open(data).convert("RGBA")
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _border_color(img: Image.Image) -> tuple[int, int, int]:
    """A cor do fundo é a que mais aparece na moldura de 1px."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    counts: dict[tuple[int, int, int], int] = {}
    for x in range(w):
        for y in (0, h - 1):
            counts[px[x, y]] = counts.get(px[x, y], 0) + 1
    for y in range(h):
        for x in (0, w - 1):
            counts[px[x, y]] = counts.get(px[x, y], 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _close_enough(a: tuple[int, int, int], b: tuple[int, int, int], tol: int) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol


def background_mask(img: Image.Image, tol: int = 24) -> Image.Image:
    """Máscara L do fundo: branco = fundo, preto = sprite.

    Só conta como fundo o que está *ligado à borda*. O olho branco de um sprite
    tem a mesma cor do fundo branco e não pode sumir — por isso não basta casar
    a cor, tem que alcançar a borda.

    O flood fill roda numa cópia reduzida (no máximo 512px de lado): num JPEG de
    4 megapixels a busca em Python levaria segundos, e a máquina de estados é a
    mesma nas duas escalas.
    """
    w, h = img.size
    scale = min(1.0, _MASK_MAX_SIDE / max(w, h))
    small = img if scale == 1.0 else img.resize(
        (max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR
    )
    sw, sh = small.size
    rgb = small.convert("RGB")
    px = rgb.load()
    bg = _border_color(small)

    seen = bytearray(sw * sh)
    queue: deque[tuple[int, int]] = deque()
    for x in range(sw):
        for y in (0, sh - 1):
            if _close_enough(px[x, y], bg, tol) and not seen[y * sw + x]:
                seen[y * sw + x] = 1
                queue.append((x, y))
    for y in range(sh):
        for x in (0, sw - 1):
            if _close_enough(px[x, y], bg, tol) and not seen[y * sw + x]:
                seen[y * sw + x] = 1
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            inside = 0 <= nx < sw and 0 <= ny < sh
            if inside and not seen[ny * sw + nx] and _close_enough(px[nx, ny], bg, tol):
                seen[ny * sw + nx] = 1
                queue.append((nx, ny))

    mask = Image.frombytes("L", (sw, sh), bytes(255 if v else 0 for v in seen))
    return mask if (sw, sh) == (w, h) else mask.resize((w, h), Image.BILINEAR)


def make_transparent(img: Image.Image, tol: int = 24) -> Image.Image:
    """Fundo vira alfa 0. O que a máscara não alcançou continua opaco."""
    out = img.convert("RGBA")
    mask = background_mask(out, tol=tol)
    alpha = out.getchannel("A")
    # Onde a máscara é branca (fundo), o alfa zera; a interpolação da máscara dá
    # uma borda suave em vez de serrilhado.
    new_alpha = Image.eval(mask, lambda v: 255 - v)
    out.putalpha(Image.composite(new_alpha, alpha, Image.eval(alpha, lambda v: 255)))
    return out


def trim(img: Image.Image, tol: int = 24) -> Image.Image:
    """Corta a moldura vazia — com alfa usa o alfa, sem alfa usa a cor da borda."""
    rgba = img.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] < 255:
        box = rgba.getbbox()
    else:
        box = Image.eval(background_mask(rgba, tol=tol), lambda v: 255 - v).getbbox()
    return rgba.crop(box) if box else rgba


def fit(img: Image.Image, size: int, pad: bool = True) -> Image.Image:
    """Reduz para caber num quadrado de `size`, sem esticar.

    Nearest-neighbour de propósito: pixel art reamostrada com filtro suave
    perde exatamente a coisa que a faz parecer pixel art.
    """
    w, h = img.size
    ratio = min(size / w, size / h)
    new = img.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.NEAREST)
    if not pad:
        return new
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(new, ((size - new.width) // 2, (size - new.height) // 2))
    return canvas


def parse_grid(grid: str) -> tuple[int, int]:
    """'4x2' -> (4, 2). Levanta ValueError no que não for isso."""
    parts = grid.lower().replace("×", "x").split("x")
    if len(parts) != 2:
        raise ValueError(grid)
    cols, rows = (int(p) for p in parts)
    if cols < 1 or rows < 1:
        raise ValueError(grid)
    return cols, rows


def slice_sheet(img: Image.Image, cols: int, rows: int) -> list[Image.Image]:
    """Corta a folha em cols*rows quadros, em ordem de leitura."""
    w, h = img.size
    fw, fh = w / cols, h / rows
    frames = []
    for r in range(rows):
        for c in range(cols):
            box = (round(c * fw), round(r * fh), round((c + 1) * fw), round((r + 1) * fh))
            frames.append(img.crop(box))
    return frames


_GIF_TRANSPARENT_INDEX = 255


def _to_gif_frame(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """RGBA -> paleta com um índice reservado para o transparente.

    GIF não tem canal alfa: tem *um* índice da paleta declarado transparente.
    Por isso a quantização usa 255 cores e guarda a 256ª para o vazio — sem
    isso o fundo do sprite vira preto no GIF.
    """
    rgba = img.convert("RGBA").resize(size, Image.NEAREST)
    palette = rgba.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=_GIF_TRANSPARENT_INDEX)
    # Alfa abaixo de 128 é vazio; meio-tom não existe em GIF, então é limiar.
    mask = rgba.getchannel("A").point(lambda v: 255 if v < 128 else 0)
    palette.paste(_GIF_TRANSPARENT_INDEX, mask=mask)
    palette.info["transparency"] = _GIF_TRANSPARENT_INDEX
    return palette


def save_gif(frames: list[Image.Image], path: Path, fps: int = 12) -> Path:
    """GIF em laço, com o fundo transparente preservado."""
    if not frames:
        raise ValueError("no frames")
    size = frames[0].size
    prepared = [_to_gif_frame(f, size) for f in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared[0].save(
        path,
        save_all=True,
        append_images=prepared[1:],
        duration=max(20, round(1000 / max(1, fps))),
        loop=0,
        disposal=2,
        transparency=_GIF_TRANSPARENT_INDEX,
        optimize=False,
    )
    return path
