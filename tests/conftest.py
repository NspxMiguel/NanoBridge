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


def sheet_bytes(cols: int, rows: int = 1) -> bytes:
    """Uma folha sintética de cols×rows quadros distintos."""
    import io

    from PIL import ImageDraw

    img = Image.new("RGB", (40 * cols, 40 * rows), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for r in range(rows):
        for c in range(cols):
            draw.rectangle(
                (c * 40 + 10, r * 40 + 10, c * 40 + 29, r * 40 + 29),
                fill=(10 + c * 40, 120, 40 + r * 30),
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
