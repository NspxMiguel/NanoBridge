"""Casos-limite do pós-processamento — os que quebram implementação ingênua."""


import pytest
from PIL import Image, ImageDraw

from nanobridge import imaging


def gradient(size=(200, 150)):
    """Fundo em degradê: não é chapado, então a remoção tem que se conter."""
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for x in range(size[0]):
        draw.line([(x, 0), (x, size[1])], fill=(200 + x % 40, 200, 210))
    draw.ellipse((60, 40, 140, 110), fill=(20, 150, 60))
    return img.convert("RGBA")


def already_transparent():
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((30, 30, 70, 70), fill=(255, 0, 0, 255))
    return img


def test_gradient_background_never_eats_the_drawing():
    out = imaging.make_transparent(gradient(), tol=30)
    assert out.getpixel((100, 75))[3] > 200, "o desenho tem que sobreviver ao degradê"


def test_already_transparent_png_survives():
    out = imaging.make_transparent(already_transparent())
    assert out.getpixel((50, 50))[3] == 255
    assert out.getpixel((2, 2))[3] == 0


def test_trim_uses_the_alpha_when_there_is_one():
    out = imaging.trim(already_transparent())
    assert 36 <= out.size[0] <= 44, out.size


def test_one_pixel_image_does_not_explode():
    out = imaging.make_transparent(Image.new("RGBA", (1, 1), (255, 255, 255, 255)))
    assert out.size == (1, 1)


def test_trim_of_a_fully_empty_image_keeps_something():
    """getbbox() devolve None num quadro vazio; cortar para nada quebraria o resto."""
    out = imaging.trim(Image.new("RGBA", (50, 50), (0, 0, 0, 0)))
    assert out.size[0] >= 1 and out.size[1] >= 1


def test_trim_of_a_full_image_changes_nothing():
    out = imaging.trim(Image.new("RGBA", (40, 40), (10, 20, 30, 255)))
    assert out.size == (40, 40)


def test_fit_pads_instead_of_upscaling_past_the_box():
    out = imaging.fit(already_transparent(), 256)
    assert out.size == (256, 256)
    box = out.getbbox()
    assert box[2] - box[0] <= 256


def test_slice_1x1_returns_the_whole_image():
    frames = imaging.slice_sheet(already_transparent(), 1, 1)
    assert len(frames) == 1 and frames[0].size == (100, 100)


def test_slice_with_more_cells_than_pixels():
    frames = imaging.slice_sheet(Image.new("RGBA", (20, 20)), 20, 20)
    assert len(frames) == 400


def test_slice_of_a_non_divisible_sheet_loses_no_column():
    """99px em 4 colunas: arredondar cada corte para dentro perderia pixels."""
    frames = imaging.slice_sheet(Image.new("RGBA", (99, 50)), 4, 1)
    assert sum(f.width for f in frames) == 99


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"", ".bin"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", ".webp"),
        (b"GIF89a\x00", ".gif"),
        (b"GIF87a\x00", ".gif"),
    ],
)
def test_sniff_extension_edges(data, expected):
    assert imaging.sniff_extension(data) == expected


def test_gif_with_a_single_frame(tmp_path):
    path = imaging.save_gif([already_transparent()], tmp_path / "one.gif", fps=5)
    with Image.open(path) as gif:
        assert gif.n_frames == 1


def test_gif_normalises_frames_of_different_sizes(tmp_path):
    frames = [already_transparent(), already_transparent().resize((60, 60))]
    path = imaging.save_gif(frames, tmp_path / "mixed.gif", fps=5)
    with Image.open(path) as gif:
        assert gif.size == (100, 100)


def test_fps_zero_does_not_produce_a_frozen_gif(tmp_path):
    """duration=0 deixa o GIF parado no primeiro quadro em vários leitores."""
    frames = [already_transparent(), already_transparent().resize((80, 80))]
    path = imaging.save_gif(frames, tmp_path / "zero.gif", fps=0)
    with Image.open(path) as gif:
        assert gif.info.get("duration", 0) >= 20


def test_gif_directory_is_created(tmp_path):
    path = imaging.save_gif([already_transparent()], tmp_path / "a" / "b" / "x.gif")
    assert path.exists()


def test_background_mask_downscales_big_images_but_keeps_the_size():
    """O flood fill roda reduzido; a máscara tem que voltar no tamanho original."""
    big = Image.new("RGBA", (2000, 1200), (255, 255, 255, 255))
    ImageDraw.Draw(big).ellipse((800, 400, 1200, 800), fill=(0, 0, 0, 255))
    mask = imaging.background_mask(big)
    assert mask.size == big.size
