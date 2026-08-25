"""Ajudantes compartilhados pelos testes."""

from PIL import Image


def opaque_colours(img: Image.Image) -> set[tuple[int, int, int]]:
    """As cores dos pixels visíveis.

    `Image.getdata()` está a caminho da remoção no Pillow 14 e
    `get_flattened_data()` só existe no Pillow novo — o projeto declara
    `pillow>=10`, então os dois caminhos precisam funcionar.
    """
    rgba = img.convert("RGBA")
    reader = getattr(rgba, "get_flattened_data", None) or rgba.getdata
    return {tuple(px)[:3] for px in reader() if tuple(px)[3] > 0}
