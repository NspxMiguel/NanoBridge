"""Pós-processamento: é o que transforma um JPEG de 2816x1536 em sprite usável.

O Nano Banana devolve uma imagem grande, em JPEG, com fundo chapado. Sprite
precisa do contrário: pequeno, PNG, fundo transparente, e às vezes cortado em
quadros. Tudo isso mora aqui, longe de qualquer coisa de rede.
"""

from __future__ import annotations

import io
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Um sprite raramente passa disso; acima daqui o flood fill fica caro à toa.
_MASK_MAX_SIDE = 512

Rgb = tuple[int, int, int]


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


@dataclass
class AtlasEntry:
    """Um sprite dentro do atlas: nome e onde ele foi colocado."""

    name: str
    x: int
    y: int
    w: int
    h: int


def pack_atlas(
    images: list[tuple[str, Image.Image]],
    padding: int = 2,
    max_width: int = 2048,
) -> tuple[Image.Image, list[AtlasEntry]]:
    """Empacota sprites soltos numa folha só, com o manifesto de onde cada um caiu.

    Nem `sheet` (que corta uma folha de ANIMAÇÃO em quadros iguais) nem uma
    pasta cheia de PNGs individuais servem direto num motor de jogo — o motor
    quer uma folha e um manifesto dizendo o retângulo de cada sprite. É isso que
    Godot, Phaser e Unity chamam de atlas/spritesheet-with-manifest, e é o que
    falta entre "gerei os sprites" e "o jogo consegue desenhar".

    Empacotamento em prateleiras (shelf packing): ordena do mais alto pro mais
    baixo, enche uma linha até estourar `max_width`, sobe pra próxima linha. Não
    é o empacotamento ótimo (isso é NP-difícil), mas é determinístico, O(n log n)
    e desperdiça pouco para o caso comum — dezenas de sprites de tamanho parecido,
    não milhares de tamanhos aleatórios.
    """
    if not images:
        raise ValueError("no images")

    # Do mais alto pro mais baixo: prateleiras mais uniformes, menos sobra no
    # fim de cada linha.
    ordered = sorted(images, key=lambda item: item[1].height, reverse=True)

    placements: list[AtlasEntry] = []
    x = y = shelf_height = 0
    canvas_width = 0
    for name, img in ordered:
        w, h = img.size
        if x > 0 and x + w > max_width:
            y += shelf_height + padding
            x = 0
            shelf_height = 0
        placements.append(AtlasEntry(name=name, x=x, y=y, w=w, h=h))
        canvas_width = max(canvas_width, x + w)
        shelf_height = max(shelf_height, h)
        x += w + padding

    canvas_height = y + shelf_height
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    by_name = dict(images)
    for entry in placements:
        canvas.paste(by_name[entry.name], (entry.x, entry.y), by_name[entry.name])

    # O manifesto sai na ordem em que o pedido chegou, não na ordem de
    # empacotamento — quem lê o JSON não deveria ter que saber o algoritmo.
    order = {name: index for index, (name, _) in enumerate(images)}
    placements.sort(key=lambda entry: order[entry.name])
    return canvas, placements


def _palette_image(colours: list[tuple[int, int, int]]) -> Image.Image:
    """Empacota a paleta no formato que o Pillow espera para quantizar.

    Pillow quer uma imagem modo "P" com a paleta preenchida até 256 entradas.
    As sobras repetem a primeira cor: entrada vazia vira preto e o preto atrai
    pixels que não deveriam ir para ele.
    """
    flat: list[int] = []
    for r, g, b in colours:
        flat.extend((r, g, b))
    first = colours[0]
    while len(flat) < 256 * 3:
        flat.extend(first)
    palette = Image.new("P", (1, 1))
    palette.putpalette(flat[: 256 * 3])
    return palette


def nearest_colour(
    colour: tuple[int, int, int], palette: list[tuple[int, int, int]]
) -> tuple[int, int, int]:
    """A cor da paleta mais próxima aos olhos, não em RGB cru."""
    return min(palette, key=lambda candidate: _perceptual_distance(colour, candidate))


def quantize_to_palette(
    img: Image.Image,
    colours: list[tuple[int, int, int]],
    dither: bool = False,
) -> Image.Image:
    """Reescreve a imagem usando só as cores da paleta, preservando o alfa.

    O casamento é PERCEPTUAL, e isso não é preciosismo. O `quantize` do Pillow
    casa em RGB cru, e em RGB cru o cinza #5F574F fica mais perto de um verde
    médio (#5CC060) do que o verde da própria paleta (#008751), porque a
    diferença no canal verde domina a conta. Na prática: um slime verde travado
    na PICO-8 saía cinza-arroxeado.

    Para não pagar isso em velocidade, a imagem primeiro é reduzida a no máximo
    256 cores no C do Pillow — um sprite de 2816×1536 são 4,3 milhões de pixels
    e comparar cada um em Python levaria dezenas de segundos —, e só essas 256
    são mapeadas na paleta, o que é instantâneo.

    `dither=False` por padrão porque pixel art quer cor chapada: o dithering do
    Floyd-Steinberg espalha o meio-tom que travar a paleta pretende remover.
    """
    if not colours:
        raise ValueError("empty palette")

    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE

    # Passo 1, no C: reduzir a no máximo 256 cores representativas.
    reduced = rgba.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=mode)
    source = reduced.getpalette() or []

    # Passo 2, em Python mas sobre 256 entradas só: cada uma vira a cor
    # perceptualmente mais próxima da paleta pedida.
    # Uma imagem com poucas cores devolve uma paleta curta: percorrer 256
    # entradas fixas estourava o índice.
    mapped: list[int] = []
    for index in range(len(source) // 3):
        entry = (source[index * 3], source[index * 3 + 1], source[index * 3 + 2])
        mapped.extend(nearest_colour(entry, colours))
    reduced.putpalette(mapped)

    out = reduced.convert("RGBA")
    out.putalpha(alpha)
    return out


def _perceptual_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Distância "redmean": mais próxima do olho que a euclidiana pura em RGB.

    Pesa os canais conforme o vermelho médio das duas cores, que é o truque
    barato e conhecido para não tratar um azul-escuro e um preto como se
    estivessem tão longe quanto um verde e um preto.
    """
    red_mean = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (
        (2 + red_mean / 256) * dr * dr
        + 4 * dg * dg
        + (2 + (255 - red_mean) / 256) * db * db
    ) ** 0.5


def extract_palette(
    img: Image.Image,
    count: int = 16,
    alpha_threshold: int = 128,
    min_distance: float = 28.0,
) -> list[tuple[int, int, int]]:
    """As cores dominantes e VISUALMENTE DISTINTAS da imagem.

    Pixels transparentes ficam de fora: num sprite recortado eles são a maioria,
    e a paleta sairia dominada pelo vazio.

    A distância mínima não é capricho. Sem ela, um sprite com uma área escura
    grande devolvia `#000000`, `#030001`, `#010005` e `#010000` como quatro
    cores — quatro pretos que ninguém distingue, ocupando o lugar das cores que
    de fato definem o personagem. Travar um elenco nessa paleta não travaria
    nada.
    """
    if count < 1:
        raise ValueError("count must be >= 1")

    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")

    # O fundo transparente vira uma cor sentinela improvável, quantiza junto e
    # sai da lista no fim — mais rápido do que filtrar pixel a pixel em Python.
    sentinel = (1, 0, 1)
    visible = Image.composite(rgb, Image.new("RGB", rgb.size, sentinel),
                              alpha.point(lambda v: 255 if v >= alpha_threshold else 0))
    # Pede bem mais bins do que o alvo: o filtro de distância descarta muitos, e
    # sem folga a paleta sairia curta.
    reduced = visible.quantize(colors=min(256, max(count * 4, 16)), method=Image.Quantize.MEDIANCUT)
    palette = reduced.getpalette() or []
    counts = sorted(reduced.getcolors() or [], reverse=True)

    out: list[tuple[int, int, int]] = []
    for _, index in counts:
        colour = (palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2])
        if colour == sentinel:
            continue
        if any(_perceptual_distance(colour, chosen) < min_distance for chosen in out):
            continue
        out.append(colour)
        if len(out) == count:
            break
    return out


def pixelate(img: Image.Image, pixels: int, zoom: int = 1) -> Image.Image:
    """Reconstrói a arte com um número exato de pixels no lado maior.

    Reduzir 2816px direto para 128px dá blocos de 4, 5 e 6 pixels misturados:
    parece pixel art de longe e desmonta no zoom, porque a grade não fecha. Aqui
    o lado maior vira exatamente `pixels`, então cada pixel da arte é um pixel de
    verdade e a grade é perfeita por construção.

    Não há detecção automática do tamanho do bloco de propósito. As tentativas
    que fiz erravam nos próprios casos de controle — uma grade sintética de 8
    saía como 9, um degradê sem grade nenhuma saía como 96 — e um detector
    errado é pior do que nenhum: ele estraga a arte sem avisar. Quem sabe a
    resolução que quer diz o número, e o resultado é sempre exato.

    `zoom` amplia por um inteiro depois, com vizinho mais próximo, para ver o
    sprite sem depender do zoom do visualizador — a grade continua fechando.
    """
    if pixels < 1:
        raise ValueError("pixels must be >= 1")
    if zoom < 1:
        raise ValueError("zoom must be >= 1")

    rgba = img.convert("RGBA")
    longest = max(rgba.size)
    ratio = pixels / longest
    native = (max(1, round(rgba.width * ratio)), max(1, round(rgba.height * ratio)))
    # BOX é a média de área: transforma um bloco numa cor só, sem inventar
    # meio-tom nas bordas como o bilinear faria.
    small = _resize_premultiplied(rgba, native)
    if zoom > 1:
        small = small.resize((small.width * zoom, small.height * zoom), Image.NEAREST)
    return small


def _resize_premultiplied(rgba: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Reduz com média de área sem sujar a cor com o que está transparente.

    Um pixel transparente ainda carrega valores de RGB, e eles costumam ser
    lixo — preto, branco, o que sobrou do fundo. Ao tirar a média de um bloco,
    esse lixo entra na conta com o mesmo peso da cor de verdade, e a borda do
    sprite ganha um halo: um slime verde saiu cinza-arroxeado.

    Pré-multiplicar resolve: cada canal é pesado pelo alfa antes da média, e
    desfeito depois. É o que qualquer compositor faz, e a razão de existir o
    conceito de "premultiplied alpha".
    """
    red, green, blue, alpha = rgba.split()
    premultiplied = [
        Image.frombytes("L", rgba.size, bytes(
            (c * a + 127) // 255
            for c, a in zip(channel.tobytes(), alpha.tobytes(), strict=True)
        )).resize(size, Image.BOX)
        for channel in (red, green, blue)
    ]
    small_alpha = alpha.resize(size, Image.BOX)

    alpha_bytes = small_alpha.tobytes()
    restored = [
        Image.frombytes("L", size, bytes(
            min(255, (c * 255 + a // 2) // a) if a else 0
            for c, a in zip(channel.tobytes(), alpha_bytes, strict=True)
        ))
        for channel in premultiplied
    ]
    return Image.merge("RGBA", (*restored, small_alpha))
