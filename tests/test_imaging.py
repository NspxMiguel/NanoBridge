import io

import pytest
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
