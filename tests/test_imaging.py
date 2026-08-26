import io

import pytest
from conftest import opaque_colours
from PIL import Image, ImageDraw

from nanobridge import imaging


def sample(size=(120, 80), bg=(255, 255, 255)):
    """Uma figura com um buraco branco dentro — o caso que quebra remoção ingênua."""
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    draw.ellipse((30, 20, 90, 60), fill=(20, 160, 60))
    draw.ellipse((50, 32, 60, 42), fill=bg)  # o "olho" branco
    return img.convert("RGBA")


def test_sniff_extension_reads_the_real_format():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="JPEG")
    assert imaging.sniff_extension(buf.getvalue()) == ".jpg"
    buf = io.BytesIO()
    Image.new("RGBA", (4, 4)).save(buf, format="PNG")
    assert imaging.sniff_extension(buf.getvalue()) == ".png"
    assert imaging.sniff_extension(b"garbage") == ".bin"


def test_transparency_keeps_enclosed_background_coloured_pixels():
    out = imaging.make_transparent(sample())
    assert out.getpixel((2, 2))[3] == 0, "o canto tinha que virar transparente"
    assert out.getpixel((55, 37))[3] > 200, "o olho branco de dentro tem que continuar opaco"
    assert out.getpixel((60, 40))[3] > 200


def test_trim_crops_to_the_drawing():
    trimmed = imaging.trim(sample())
    assert trimmed.size[0] < 120 and trimmed.size[1] < 80
    assert trimmed.size[0] >= 60


def test_fit_pads_to_a_square_and_never_upscales_beyond_the_box():
    fitted = imaging.fit(sample(), 64)
    assert fitted.size == (64, 64)
    unpadded = imaging.fit(sample(), 64, pad=False)
    assert max(unpadded.size) == 64


@pytest.mark.parametrize("grid,expected", [("4x2", (4, 2)), ("1X1", (1, 1)), ("3×3", (3, 3))])
def test_parse_grid(grid, expected):
    assert imaging.parse_grid(grid) == expected


@pytest.mark.parametrize("bad", ["4", "4x", "x2", "0x3", "-1x2", "axb"])
def test_parse_grid_rejects_junk(bad):
    with pytest.raises(ValueError):
        imaging.parse_grid(bad)


def test_slice_sheet_covers_the_whole_image():
    img = Image.new("RGBA", (100, 50))
    frames = imaging.slice_sheet(img, 4, 2)
    assert len(frames) == 8
    assert sum(f.width for f in frames[:4]) == 100
    assert sum(f.height for f in frames[::4]) == 50


def test_save_gif_keeps_a_transparent_index(tmp_path):
    # Quadros diferentes de propósito: o Pillow funde quadros idênticos, e um
    # GIF de 3 quadros iguais volta com n_frames == 1.
    frames = [
        imaging.make_transparent(sample(bg=(255, 255, 255)).resize((120, 80 - i * 6)))
        for i in range(3)
    ]
    path = imaging.save_gif(frames, tmp_path / "a.gif", fps=10)
    with Image.open(path) as gif:
        assert gif.n_frames == 3
        assert gif.info.get("transparency") == 255


def test_save_gif_refuses_an_empty_list(tmp_path):
    with pytest.raises(ValueError):
        imaging.save_gif([], tmp_path / "a.gif")


def solid(size, colour):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((0, 0, size[0] - 1, size[1] - 1), fill=colour)
    return img


def test_pack_atlas_places_everything_without_overlap():
    images = [
        ("tall", solid((20, 60), (255, 0, 0, 255))),
        ("wide", solid((60, 20), (0, 255, 0, 255))),
        ("small", solid((10, 10), (0, 0, 255, 255))),
    ]
    canvas, entries = imaging.pack_atlas(images, padding=2)
    assert {e.name for e in entries} == {"tall", "wide", "small"}
    boxes = [(e.x, e.y, e.x + e.w, e.y + e.h) for e in entries]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            assert not overlap, f"{a} overlaps {b}"
    for e in entries:
        assert e.x + e.w <= canvas.width
        assert e.y + e.h <= canvas.height


def test_pack_atlas_manifest_follows_input_order_not_packing_order():
    images = [("z", solid((10, 40), (1, 1, 1, 255))), ("a", solid((10, 10), (2, 2, 2, 255)))]
    _, entries = imaging.pack_atlas(images)
    assert [e.name for e in entries] == ["z", "a"]


def test_pack_atlas_wraps_to_a_new_shelf_past_max_width():
    images = [(f"s{i}", solid((100, 40), (i, i, i, 255))) for i in range(5)]
    _, entries = imaging.pack_atlas(images, padding=0, max_width=250)
    rows = {e.y for e in entries}
    assert len(rows) > 1, "cinco sprites de 100px em max_width=250 têm que quebrar linha"


def test_pack_atlas_pastes_the_real_pixels_not_just_the_boxes():
    images = [("red", solid((20, 20), (255, 0, 0, 255))), ("blue", solid((20, 20), (0, 0, 255, 255)))]
    canvas, entries = imaging.pack_atlas(images, padding=0)
    red = entries[0] if entries[0].name == "red" else entries[1]
    assert canvas.getpixel((red.x + 5, red.y + 5)) == (255, 0, 0, 255)


def test_pack_atlas_rejects_an_empty_list():
    with pytest.raises(ValueError):
        imaging.pack_atlas([])


def test_pack_atlas_respects_padding():
    images = [("a", solid((10, 10), (1, 1, 1, 255))), ("b", solid((10, 10), (2, 2, 2, 255)))]
    _, entries = imaging.pack_atlas(images, padding=5)
    a, b = sorted(entries, key=lambda e: e.x)
    assert b.x - (a.x + a.w) == 5


def test_quantize_uses_only_palette_colours():
    src = Image.new("RGBA", (40, 40))
    ImageDraw.Draw(src).rectangle((0, 0, 39, 39), fill=(123, 45, 200, 255))
    out = imaging.quantize_to_palette(src, [(0, 0, 0), (255, 255, 255)])
    used = opaque_colours(out)
    assert used <= {(0, 0, 0), (255, 255, 255)}


def test_quantize_preserves_alpha():
    src = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    ImageDraw.Draw(src).ellipse((5, 5, 15, 15), fill=(200, 30, 30, 255))
    out = imaging.quantize_to_palette(src, [(255, 0, 0), (0, 0, 255)])
    assert out.getpixel((0, 0))[3] == 0, "o vazio tem que continuar vazio"
    assert out.getpixel((10, 10))[3] == 255


def test_quantize_rejects_an_empty_palette():
    with pytest.raises(ValueError):
        imaging.quantize_to_palette(Image.new("RGBA", (4, 4)), [])


def test_quantize_maps_to_the_nearest_colour_not_an_arbitrary_one():
    src = Image.new("RGBA", (4, 4), (250, 250, 250, 255))
    out = imaging.quantize_to_palette(src, [(0, 0, 0), (255, 255, 255)])
    assert out.getpixel((0, 0))[:3] == (255, 255, 255)


def test_extract_palette_ignores_transparent_pixels():
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((10, 10, 50, 50), fill=(20, 200, 90, 255))
    colours = imaging.extract_palette(img, count=3)
    assert colours
    # nada de preto vindo do fundo transparente
    assert all(c != (0, 0, 0) for c in colours), colours


def test_extract_palette_returns_visually_distinct_colours():
    """Sem filtro de distância um sprite escuro devolvia quatro pretos iguais."""
    img = Image.new("RGBA", (80, 80), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    for i, shade in enumerate([(1, 1, 1), (3, 0, 1), (2, 2, 0), (250, 30, 30)]):
        draw.rectangle((i * 20, 0, i * 20 + 19, 79), fill=shade)
    colours = imaging.extract_palette(img, count=4)
    for i, a in enumerate(colours):
        for b in colours[i + 1 :]:
            assert imaging._perceptual_distance(a, b) >= 28.0, f"{a} e {b} são a mesma cor"


def test_extract_palette_respects_the_count():
    img = Image.new("RGBA", (60, 20))
    draw = ImageDraw.Draw(img)
    for i, colour in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]):
        draw.rectangle((i * 15, 0, i * 15 + 14, 19), fill=(*colour, 255))
    assert len(imaging.extract_palette(img, count=2)) <= 2


def test_extract_palette_rejects_a_bad_count():
    with pytest.raises(ValueError):
        imaging.extract_palette(Image.new("RGBA", (4, 4)), count=0)


def test_perceptual_distance_is_zero_for_identical_colours():
    assert imaging._perceptual_distance((10, 20, 30), (10, 20, 30)) == 0


def test_pixelate_hits_the_exact_requested_size():
    src = Image.new("RGBA", (2816, 1536), (10, 20, 30, 255))
    out = imaging.pixelate(src, 48)
    assert max(out.size) == 48


def test_pixelate_keeps_the_aspect_ratio():
    src = Image.new("RGBA", (400, 200), (10, 20, 30, 255))
    out = imaging.pixelate(src, 40)
    assert out.size == (40, 20)


def test_zoom_produces_a_perfect_grid():
    """O ponto do comando: depois do zoom cada pixel da arte é um bloco
    exatamente uniforme. Era isso que a redução direta não dava."""
    src = Image.new("RGBA", (300, 300))
    draw = ImageDraw.Draw(src)
    for i in range(10):
        draw.rectangle((i * 30, 0, i * 30 + 29, 299), fill=(i * 25, 100, 200, 255))

    zoom = 6
    out = imaging.pixelate(src, 10, zoom=zoom)
    assert out.size == (60, 60)
    for block_x in range(out.width // zoom):
        for block_y in range(out.height // zoom):
            corner = out.getpixel((block_x * zoom, block_y * zoom))
            for dx in range(zoom):
                for dy in range(zoom):
                    assert out.getpixel((block_x * zoom + dx, block_y * zoom + dy)) == corner


def test_pixelate_preserves_transparency():
    src = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(src).ellipse((25, 25, 75, 75), fill=(200, 30, 30, 255))
    out = imaging.pixelate(src, 20)
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((10, 10))[3] > 0


def test_pixelate_never_produces_a_zero_dimension():
    src = Image.new("RGBA", (2000, 10), (1, 2, 3, 255))
    out = imaging.pixelate(src, 8)
    assert out.width >= 1 and out.height >= 1


@pytest.mark.parametrize("pixels,zoom", [(0, 1), (-1, 1), (10, 0), (10, -2)])
def test_pixelate_rejects_bad_arguments(pixels, zoom):
    with pytest.raises(ValueError):
        imaging.pixelate(Image.new("RGBA", (20, 20)), pixels, zoom=zoom)


def test_quantize_matches_perceptually_not_in_raw_rgb():
    """Bug real: em RGB cru o cinza #5F574F fica mais perto de um verde médio
    do que o verde da paleta, e um slime verde na PICO-8 saía cinza."""
    from nanobridge import palettes

    green = Image.new("RGBA", (16, 16), (92, 192, 96, 255))
    out = imaging.quantize_to_palette(green, palettes.resolve("pico8"))
    chosen = out.getpixel((8, 8))[:3]
    assert chosen != (95, 87, 79), "escolheu o cinza de novo"
    assert chosen[1] > chosen[0] and chosen[1] > chosen[2], f"não é verde: {chosen}"


def test_nearest_colour_prefers_hue_over_raw_distance():
    grey = (95, 87, 79)
    green = (0, 135, 81)
    assert imaging.nearest_colour((92, 192, 96), [grey, green]) == green


def test_quantize_is_fast_on_a_large_image():
    """A quantização perceptual roda sobre 256 cores, não sobre os pixels."""
    import time

    from nanobridge import palettes

    big = Image.new("RGBA", (1200, 900), (92, 192, 96, 255))
    started = time.monotonic()
    imaging.quantize_to_palette(big, palettes.resolve("endesga32"))
    assert time.monotonic() - started < 2.0


def _gradient(size=(120, 120)):
    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (min(255, x * 2), 80, 120))
    return img


def _periodic(size=(120, 120)):
    import math

    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            v = int(127 + 120 * math.sin(2 * math.pi * x / size[0]) * math.sin(2 * math.pi * y / size[1]))
            img.putpixel((x, y), (v, v, v))
    return img


def test_seam_error_is_large_where_the_edges_do_not_meet():
    assert imaging.seam_error(_gradient())["horizontal"] > 20


def test_seam_error_is_small_on_something_that_already_tiles():
    seam = imaging.seam_error(_periodic())
    assert seam["horizontal"] < 3 and seam["vertical"] < 3


def test_make_tileable_actually_reduces_the_seam():
    before = imaging.seam_error(_gradient())["horizontal"]
    after = imaging.seam_error(imaging.make_tileable(_gradient()))["horizontal"]
    assert after < before / 10, f"antes {before}, depois {after}"


def test_make_tileable_keeps_the_size():
    out = imaging.make_tileable(_gradient((80, 60)))
    assert out.size == (80, 60)


@pytest.mark.parametrize("blend", [0, -0.1, 0.5, 1.0])
def test_make_tileable_rejects_a_bad_blend(blend):
    with pytest.raises(ValueError):
        imaging.make_tileable(_gradient(), blend=blend)


def test_seam_error_on_a_tiny_image_does_not_explode():
    assert imaging.seam_error(Image.new("RGB", (2, 2))) == {"horizontal": 0.0, "vertical": 0.0}
