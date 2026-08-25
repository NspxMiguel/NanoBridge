"""Paletas fixas, e a paleta extraída de uma imagem.

Por que isto existe: dois sprites gerados separadamente quase nunca parecem do
mesmo jogo. O modelo escolhe verdes ligeiramente diferentes a cada vez, e o
elenco fica com aquela cara de "cada um veio de um lugar". Travar a paleta
resolve de forma determinística, sem depender de o modelo obedecer ao prompt —
e sem gastar cota, porque é feito depois, no disco.

Os valores das paletas conhecidas são os públicos e amplamente reproduzidos de
cada plataforma/autor: PICO-8 (Lexaloffle), Game Boy (DMG), CGA e Commodore 64
(hardware), Sweetie 16 (GrafxKid) e Endesga 32 (ENDESGA).
"""

from __future__ import annotations

from pathlib import Path

Rgb = tuple[int, int, int]

BUILTIN: dict[str, list[str]] = {
    # 16 cores, a mais usada em pixel art moderna
    "pico8": [
        "#000000", "#1D2B53", "#7E2553", "#008751", "#AB5236", "#5F574F",
        "#C2C3C7", "#FFF1E8", "#FF004D", "#FFA300", "#FFEC27", "#00E436",
        "#29ADFF", "#83769C", "#FF77A8", "#FFCCAA",
    ],
    # 4 tons de verde do Game Boy original
    "gameboy": ["#0F380F", "#306230", "#8BAC0F", "#9BBC0F"],
    # 4 tons de cinza, para quem quer a silhueta antes da cor
    "gameboy-pocket": ["#000000", "#555555", "#AAAAAA", "#FFFFFF"],
    "cga": [
        "#000000", "#0000AA", "#00AA00", "#00AAAA", "#AA0000", "#AA00AA",
        "#AA5500", "#AAAAAA", "#555555", "#5555FF", "#55FF55", "#55FFFF",
        "#FF5555", "#FF55FF", "#FFFF55", "#FFFFFF",
    ],
    "c64": [
        "#000000", "#FFFFFF", "#880000", "#AAFFEE", "#CC44CC", "#00CC55",
        "#0000AA", "#EEEE77", "#DD8855", "#664400", "#FF7777", "#333333",
        "#777777", "#AAFF66", "#0088FF", "#BBBBBB",
    ],
    "sweetie16": [
        "#1A1C2C", "#5D275D", "#B13E53", "#EF7D57", "#FFCD75", "#A7F070",
        "#38B764", "#257179", "#29366F", "#3B5DC9", "#41A6F6", "#73EFF7",
        "#F4F4F4", "#94B0C2", "#566C86", "#333C57",
    ],
    "endesga32": [
        "#BE4A2F", "#D77643", "#EAD4AA", "#E4A672", "#B86F50", "#733E39",
        "#3E2731", "#A22633", "#E43B44", "#F77622", "#FEAE34", "#FEE761",
        "#63C74D", "#3E8948", "#265C42", "#193C3E", "#124E89", "#0099DB",
        "#2CE8F5", "#FFFFFF", "#C0CBDC", "#8B9BB4", "#5A6988", "#3A4466",
        "#262B44", "#181425", "#FF0044", "#68386C", "#B55088", "#F6757A",
        "#E8B796", "#C28569",
    ],
    # Cinza puro: útil para conferir se a silhueta funciona sem a cor ajudar
    "grayscale8": [
        "#000000", "#242424", "#484848", "#6D6D6D",
        "#919191", "#B6B6B6", "#DADADA", "#FFFFFF",
    ],
}


def hex_to_rgb(value: str) -> Rgb:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"cor inválida / invalid colour: {value}")
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError as exc:
        raise ValueError(f"cor inválida / invalid colour: {value}") from exc


def rgb_to_hex(colour: Rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*colour)


def names() -> list[str]:
    return sorted(BUILTIN)


def resolve(spec: str | list[str] | Path) -> list[Rgb]:
    """Aceita nome embutido, lista de cores, ou caminho de arquivo.

    O arquivo é uma cor por linha (`#RRGGBB`), que é o formato que a maioria dos
    editores de pixel art exporta como `.hex` — e que dá para escrever à mão.
    """
    if isinstance(spec, list):
        return [hex_to_rgb(c) for c in spec]

    text = str(spec)
    if text.lower() in BUILTIN:
        return [hex_to_rgb(c) for c in BUILTIN[text.lower()]]

    path = Path(text).expanduser()
    if path.exists():
        colours: list[Rgb] = []
        for line in path.read_text().splitlines():
            stripped = line.split("#comment")[0].strip()
            if not stripped or stripped.startswith((";", "//")):
                continue
            colours.append(hex_to_rgb(stripped))
        if not colours:
            raise ValueError(f"nenhuma cor no arquivo / no colours in file: {path}")
        return colours

    # Lista separada por vírgula, para caber numa linha de comando
    if "," in text:
        return [hex_to_rgb(part) for part in text.split(",") if part.strip()]

    raise ValueError(
        f"paleta desconhecida / unknown palette: {text} "
        f"(embutidas / built-in: {', '.join(names())})"
    )


def save(colours: list[Rgb], path: Path) -> Path:
    """Grava no mesmo formato `.hex` que `resolve` lê de volta."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rgb_to_hex(c) for c in colours) + "\n")
    return path
