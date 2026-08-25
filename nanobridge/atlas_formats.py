"""O mesmo atlas, escrito no formato que cada motor sabe ler.

Um manifesto próprio é fácil de gerar e chato de usar: quem está no Godot quer
um `.tres`, quem está no Phaser quer o JSON do TexturePacker, quem está na web
quer CSS. Traduzir aqui custa quase nada e é a diferença entre "tem um JSON" e
"dá pra usar".
"""

from __future__ import annotations

import json
from pathlib import Path

from .imaging import AtlasEntry

FORMATS = ("nanobridge", "phaser", "texturepacker", "godot", "css", "aseprite")


def _frames(entries: list[AtlasEntry]) -> dict:
    return {
        entry.name: {
            "frame": {"x": entry.x, "y": entry.y, "w": entry.w, "h": entry.h},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": entry.w, "h": entry.h},
            "sourceSize": {"w": entry.w, "h": entry.h},
        }
        for entry in entries
    }


def _meta(image: str, width: int, height: int) -> dict:
    return {
        "app": "nanobridge",
        "image": image,
        "format": "RGBA8888",
        "size": {"w": width, "h": height},
        "scale": "1",
    }


def nanobridge(entries: list[AtlasEntry], image: str, width: int, height: int) -> str:
    """O formato simples do projeto: uma lista, sem cerimônia."""
    return json.dumps(
        {
            "image": image,
            "size": {"w": width, "h": height},
            "sprites": [
                {"name": e.name, "x": e.x, "y": e.y, "w": e.w, "h": e.h} for e in entries
            ],
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def texturepacker(entries: list[AtlasEntry], image: str, width: int, height: int) -> str:
    """JSON "hash" do TexturePacker — o que Phaser, PixiJS e Cocos carregam."""
    return json.dumps(
        {"frames": _frames(entries), "meta": _meta(image, width, height)},
        indent=2,
        ensure_ascii=False,
    ) + "\n"


#: Phaser lê exatamente o JSON hash do TexturePacker; separar os dois nomes é só
#: para quem procura pelo nome do motor em vez do nome da ferramenta.
phaser = texturepacker


def godot(entries: list[AtlasEntry], image: str, width: int, height: int) -> str:
    """Um `.tres` com um AtlasTexture por sprite.

    O `ext_resource` aponta para a imagem ao lado por caminho relativo, que é o
    que funciona quando a pasta inteira é arrastada para dentro do projeto.
    """
    lines = [
        f'[gd_resource type="Resource" load_steps={len(entries) + 2} format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{image}" id="1"]',
        "",
    ]
    for index, entry in enumerate(entries, start=1):
        lines += [
            f'[sub_resource type="AtlasTexture" id="{index}"]',
            'atlas = ExtResource("1")',
            f"region = Rect2({entry.x}, {entry.y}, {entry.w}, {entry.h})",
            "",
        ]
    lines += ["[resource]", "sprites = {"]
    for index, entry in enumerate(entries, start=1):
        lines.append(f'    "{entry.name}": SubResource("{index}"),')
    lines += ["}", ""]
    return "\n".join(lines)


def css(entries: list[AtlasEntry], image: str, width: int, height: int) -> str:
    """Sprite sheet de CSS: uma classe por sprite, com background-position."""
    lines = [
        "/* nanobridge sprite atlas */",
        ".sprite {",
        f"  background-image: url('{image}');",
        f"  background-size: {width}px {height}px;",
        "  background-repeat: no-repeat;",
        "  display: inline-block;",
        "  image-rendering: pixelated;",
        "}",
        "",
    ]
    for entry in entries:
        lines += [
            f".sprite--{entry.name} {{",
            f"  width: {entry.w}px;",
            f"  height: {entry.h}px;",
            # "-0px" é válido e feio; alguém vai ler este arquivo.
            f"  background-position: {-entry.x}px {-entry.y}px;",
            "}",
            "",
        ]
    return "\n".join(lines)


def aseprite(entries: list[AtlasEntry], image: str, width: int, height: int) -> str:
    """JSON do Aseprite — o mesmo esqueleto, com a lista de "frames" em array."""
    return json.dumps(
        {
            "frames": [
                {
                    "filename": e.name,
                    "frame": {"x": e.x, "y": e.y, "w": e.w, "h": e.h},
                    "rotated": False,
                    "trimmed": False,
                    "spriteSourceSize": {"x": 0, "y": 0, "w": e.w, "h": e.h},
                    "sourceSize": {"w": e.w, "h": e.h},
                    "duration": 100,
                }
                for e in entries
            ],
            "meta": _meta(image, width, height),
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


_WRITERS = {
    "nanobridge": (nanobridge, ".json"),
    "phaser": (phaser, ".json"),
    "texturepacker": (texturepacker, ".json"),
    "godot": (godot, ".tres"),
    "css": (css, ".css"),
    "aseprite": (aseprite, ".json"),
}


def suffix_for(fmt: str) -> str:
    try:
        return _WRITERS[fmt][1]
    except KeyError:
        raise ValueError(f"formato desconhecido / unknown format: {fmt}") from None


def render(fmt: str, entries: list[AtlasEntry], image: str, width: int, height: int) -> str:
    try:
        writer = _WRITERS[fmt][0]
    except KeyError:
        raise ValueError(
            f"formato desconhecido / unknown format: {fmt} "
            f"(conhecidos / known: {', '.join(FORMATS)})"
        ) from None
    return writer(entries, image, width, height)


def write(
    fmt: str,
    entries: list[AtlasEntry],
    image_path: Path,
    width: int,
    height: int,
    taken: set[Path] | None = None,
) -> Path:
    """Grava o manifesto ao lado da imagem, com a extensão certa do formato.

    Formatos diferentes podem querer a mesma extensão — `nanobridge`, `phaser` e
    `aseprite` são todos `.json`. Pedir dois deles gravava um por cima do outro
    em silêncio, então quem já foi escrito nesta chamada entra em `taken` e o
    próximo ganha o nome do formato no arquivo.
    """
    suffix = suffix_for(fmt)
    target = image_path.with_suffix(suffix)
    if target == image_path or (taken and target in taken):
        target = image_path.with_name(f"{image_path.stem}-{fmt}{suffix}")
    target.write_text(render(fmt, entries, image_path.name, width, height))
    if taken is not None:
        taken.add(target)
    return target
