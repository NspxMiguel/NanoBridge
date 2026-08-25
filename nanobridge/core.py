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

from . import atlas_formats, imaging, palettes
from .backends import Backend, pick
from .config import default_out_dir
from .errors import NoImageError
from .i18n import t

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
    "pixel": (
        "Pixel art, low resolution look, chunky pixels, limited palette, "
        "crisp 1px black outline, no anti-aliasing"
    ),
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


def existing_path(path: str | Path) -> Path:
    """Caminho de entrada que precisa existir, com a mensagem traduzida.

    Deixar o Pillow falhar dá a mensagem do sistema operacional, em inglês,
    dizendo "No such file or directory" — enquanto o resto da ferramenta fala a
    língua do usuário e dá o caminho já expandido.
    """
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(t("err.file_missing", path=str(resolved)))
    return resolved


def safe_stem(name: str, fallback: str = "nanobridge") -> str:
    """Nome de arquivo vindo de fora nunca pode escapar da pasta de saída.

    Quem preenche `name` no servidor MCP é um modelo. `../../algo` gravaria fora
    de `out_dir` sem ninguém perceber — então só sobra o nome final, e ele passa
    pelo mesmo filtro do slug.
    """
    return slugify(Path(str(name)).name, fallback=fallback)


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Caminho livre: `x.png`, senão `x-2.png`, `x-3.png`…

    Gerar duas vezes com o mesmo assunto é o fluxo normal — o modelo não repete a
    imagem, e a segunda apagava a primeira em silêncio.
    """
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    for counter in range(2, 1000):
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(str(directory / stem))


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


# Quando o modelo responde texto em vez de imagem, há dois motivos bem
# diferentes e só um deles vale insistir:
#
#   - ele leu o pedido como conversa ("x" → explica o que é a letra X). Um
#     empurrão dizendo "isto é um pedido de imagem" resolve quase sempre.
#   - ele recusou de propósito (política de conteúdo, direitos). Insistir aqui
#     não muda nada e queima cota — cada tentativa custa créditos do plano dele.
#
# Por isso a recusa é detectada e encerra na hora, em vez de virar três
# tentativas idênticas.
#
# As frases são deliberadamente longas. Um primeiro rascunho tinha "against" e
# "policy" soltos, e isso transforma "a knight leaning against a stone wall" numa
# recusa — o modelo costuma repetir o pedido na resposta, então uma palavra comum
# na lista desliga o retry justamente nos prompts normais.
_REFUSALS = (
    "can't create",
    "cannot create",
    "can't generate",
    "cannot generate",
    "can't help with",
    "cannot help with",
    "won't be able to",
    "unable to create",
    "unable to generate",
    "i'm not able to",
    "goes against",
    "violates",
    "content policy",
    "safety policy",
    "not allowed to",
    "não posso criar",
    "nao posso criar",
    "não posso gerar",
    "nao posso gerar",
    "não consigo criar",
    "nao consigo criar",
)

#: Empurrão progressivo: o primeiro é gentil, o segundo é explícito. Nada de
#: repetir o mesmo prompt — se ele não bastou da primeira vez, não basta na
#: segunda.
_NUDGES = (
    "Generate an image for this. Reply with the image itself, not with text.\n\n",
    "IMAGE REQUEST. Output exactly one generated image and no explanation, "
    "no description, no questions.\n\n",
)


def looks_like_a_refusal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _REFUSALS)


async def _generate_with_retry(
    backend: Backend,
    prompt: str,
    *,
    files: list[Path] | None,
    model: str | None,
    conversation: str | None,
    retries: int,
):
    """Pede a imagem, e insiste quando a resposta veio como texto por engano.

    Devolve o `Result` da primeira tentativa que trouxe imagem. Se todas
    falharem, levanta `NoImageError` com o texto da ÚLTIMA tentativa — que é o
    que explica melhor por que não deu.
    """
    attempt_prompt = prompt
    last_text = ""
    for attempt in range(retries + 1):
        result = await backend.generate(
            attempt_prompt, files=files, model=model, conversation=conversation
        )
        if result.images:
            return result
        last_text = result.text or ""
        if looks_like_a_refusal(last_text):
            break
        if attempt < retries:
            attempt_prompt = _NUDGES[min(attempt, len(_NUDGES) - 1)] + prompt
            # Uma conversa que já entendeu errado tende a insistir no erro; a
            # tentativa seguinte começa limpa.
            conversation = None
    raise NoImageError(last_text)


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
    retries: int = 2,
    palette: str | list[str] | None = None,
    dither: bool = False,
) -> Generated:
    # A conferência do arquivo mora aqui, antes de escolher canal e antes de
    # subir o cliente do Gemini (que custa uma ida à rede): caminho errado tem
    # que falhar de graça, e todo canal herda a mesma checagem.
    checked = [existing_path(f) for f in (files or [])]
    chosen = backend or pick(backend_name)
    result = await _generate_with_retry(
        chosen,
        prompt,
        files=checked or None,
        model=model,
        conversation=conversation,
        retries=retries,
    )

    target = Path(out_dir or default_out_dir()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(name) if name else f"{slugify(prompt)}-{datetime.now().strftime('%H%M%S')}"
    # Resolver a paleta ANTES de gastar Pillow em cada imagem, e antes de
    # escrever qualquer arquivo: nome de paleta errado tem que falhar de cara,
    # não depois de meia dúzia de sprites gravados.
    colours = palettes.resolve(palette) if palette else None
    needs_pillow = bool(transparent or trim or size or colours)

    paths: list[Path] = []
    for index, raw in enumerate(result.images):
        part = "" if len(result.images) == 1 else f"-{index + 1}"
        if needs_pillow:
            img = imaging.open_image(raw)
            if transparent:
                img = imaging.make_transparent(img, tol=tolerance)
            if trim:
                img = imaging.trim(img, tol=tolerance)
            if size:
                img = imaging.fit(img, size, pad=False)
            if colours:
                # Depois de redimensionar: reduzir a imagem mistura pixels
                # vizinhos e reintroduz cores fora da paleta.
                img = imaging.quantize_to_palette(img, colours, dither=dither)
            path = unique_path(target, f"{stem}{part}", ".png")
            img.save(path)
        else:
            path = unique_path(target, f"{stem}{part}", imaging.sniff_extension(raw))
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
    stem = safe_stem(kwargs.pop("name", None) or f"sheet-{slugify(subject)}")
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
        generated.paths = [source, *generated.paths[1:]]

    # A pasta de quadros leva o nome do arquivo que saiu, não o pedido: rodar de
    # novo com uma grade menor deixaria quadros da rodada anterior lá dentro,
    # e ninguém saberia quais são de qual.
    frames_dir = source.parent / f"{source.stem}-frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("*.png"):
        stale.unlink()
    frame_paths: list[Path] = []
    frames = imaging.slice_sheet(full, cols, rows)
    for index, frame in enumerate(frames, start=1):
        if frame_size:
            frame = imaging.fit(frame, frame_size)
        path = frames_dir / f"{source.stem}-{index:02d}.png"
        frame.save(path)
        frame_paths.append(path)

    generated.frames = frame_paths
    generated.grid = (cols, rows)
    if gif and frame_paths:
        generated.gif = imaging.save_gif(
            [imaging.open_image(p) for p in frame_paths], source.with_suffix(".gif"), fps=fps
        )
    return generated


@dataclass
class AtlasResult:
    """Onde o atlas e os manifestos ficaram, e o que eles dizem."""

    path: Path
    manifest_path: Path
    entries: list[imaging.AtlasEntry] = field(default_factory=list)
    manifests: dict[str, Path] = field(default_factory=dict)


def build_atlas(
    images: list[Path],
    *,
    out_dir: Path | None = None,
    name: str | None = None,
    padding: int = 2,
    max_width: int = 2048,
    formats: list[str] | None = None,
) -> AtlasResult:
    """Empacota sprites já existentes num atlas + manifesto JSON.

    Puramente local — nenhum canal, nenhuma cota, e serve imagem de qualquer
    origem, não só do que este projeto gerou. O nome de cada sprite no
    manifesto é o nome do arquivo sem extensão, porque é o identificador que já
    existe e que o motor de jogo vai reconhecer.
    """
    checked = [existing_path(p) for p in images]
    if not checked:
        raise ValueError("no images")

    loaded = [(path.stem, imaging.open_image(path)) for path in checked]
    canvas, entries = imaging.pack_atlas(loaded, padding=padding, max_width=max_width)

    target = Path(out_dir or default_out_dir()).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(name) if name else "atlas"
    image_path = unique_path(target, stem, ".png")
    canvas.save(image_path)

    # Formatos são validados antes de qualquer escrita: um nome errado no fim da
    # lista não pode deixar metade dos manifestos no disco.
    wanted = list(formats or ["nanobridge"])
    for fmt in wanted:
        atlas_formats.suffix_for(fmt)

    manifests: dict[str, Path] = {}
    taken: set[Path] = set()
    for fmt in wanted:
        manifests[fmt] = atlas_formats.write(
            fmt, entries, image_path, canvas.width, canvas.height, taken=taken
        )

    return AtlasResult(
        path=image_path,
        manifest_path=manifests[wanted[0]],
        entries=entries,
        manifests=manifests,
    )


def palette_from_image(image: str | Path, count: int = 16) -> list[imaging.Rgb]:
    """A paleta de um sprite já feito, para travar o resto do elenco nela."""
    return imaging.extract_palette(imaging.open_image(existing_path(image)), count=count)


def apply_palette(
    image: str | Path,
    palette: str | list[str],
    *,
    out: Path | None = None,
    dither: bool = False,
) -> Path:
    """Reescreve uma imagem do disco na paleta pedida. Local, sem cota."""
    source = existing_path(image)
    colours = palettes.resolve(palette)
    result = imaging.quantize_to_palette(imaging.open_image(source), colours, dither=dither)
    target = Path(out) if out else source.with_name(f"{source.stem}-palette.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    result.save(target)
    return target
