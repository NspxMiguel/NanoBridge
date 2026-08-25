import asyncio
import io

import pytest
from PIL import Image

from nanobridge import core
from nanobridge.backends.base import Backend, Result
from nanobridge.errors import NoImageError


def png(size=(64, 64), colour=(10, 200, 40)) -> bytes:
    img = Image.new("RGB", size, (255, 255, 255))
    img.paste(Image.new("RGB", (30, 30), colour), (17, 17))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeBackend(Backend):
    """Canal falso: os testes de core não podem depender de rede nem de cota."""

    name = "fake"

    def __init__(self, images=None, text="", sheet_grid=None):
        self.images = images if images is not None else [png()]
        self.text = text
        self.calls = []

    def available(self) -> bool:
        return True

    def status(self) -> str:
        return "fake"

    async def generate(self, prompt, files=None, model=None, conversation=None):
        self.calls.append({"prompt": prompt, "files": files, "conversation": conversation})
        return Result(images=list(self.images), text=self.text, backend=self.name, conversation="c1")


def test_slugify_strips_accents_and_punctuation():
    assert core.slugify("Um Slime Verde Fofão!!") == "um-slime-verde-fofao"
    assert core.slugify("///") == "nanobridge"
    assert len(core.slugify("x" * 300)) <= 48


def test_style_text_falls_back_to_free_text():
    assert core.style_text("pixel").startswith("Pixel art")
    assert core.style_text("como um vitral") == "como um vitral"
    assert core.style_text(None) == core.STYLES[core.DEFAULT_STYLE]


def test_sprite_prompt_forbids_what_ruins_a_sprite():
    prompt = core.SPRITE_TEMPLATE.format(subject="a slime", style=core.style_text("pixel"))
    for banned in ("no shadow", "no text", "no border", "white background"):
        assert banned in prompt.lower()


def test_generate_writes_the_file_and_reports_the_conversation(tmp_path):
    backend = FakeBackend()
    result = asyncio.run(core.generate("a slime", backend=backend, out_dir=tmp_path, name="s"))
    assert result.paths == [tmp_path / "s.png"]
    assert result.paths[0].exists()
    assert result.conversation == "c1"


def test_generate_raises_when_no_image_comes_back(tmp_path):
    backend = FakeBackend(images=[], text="I cannot draw that")
    with pytest.raises(NoImageError) as err:
        asyncio.run(core.generate("x", backend=backend, out_dir=tmp_path))
    assert "cannot draw" in str(err.value)


def test_several_images_get_numbered(tmp_path):
    backend = FakeBackend(images=[png(), png(colour=(200, 10, 10))])
    result = asyncio.run(core.generate("x", backend=backend, out_dir=tmp_path, name="s"))
    assert [p.name for p in result.paths] == ["s-1.png", "s-2.png"]


def test_sprite_defaults_to_transparent_and_trimmed(tmp_path):
    backend = FakeBackend()
    result = asyncio.run(core.sprite("a slime", backend=backend, out_dir=tmp_path))
    with Image.open(result.paths[0]) as img:
        assert img.mode == "RGBA"
        assert img.size == (30, 30), "devia ter cortado a moldura branca"
        assert img.getchannel("A").getextrema()[1] == 255


def test_edit_passes_the_reference_file(tmp_path):
    source = tmp_path / "in.png"
    source.write_bytes(png())
    backend = FakeBackend()
    asyncio.run(core.edit(source, "make it blue", backend=backend, out_dir=tmp_path))
    assert backend.calls[0]["files"] == [source]


def test_sheet_slices_the_grid_and_builds_a_gif(tmp_path):
    grid_image = Image.new("RGB", (160, 80), (255, 255, 255))
    for index in range(8):
        col, row = index % 4, index // 4
        grid_image.paste(
            Image.new("RGB", (20, 20), (10 + index * 20, 120, 40)),
            (col * 40 + 10, row * 40 + 10),
        )
    buf = io.BytesIO()
    grid_image.save(buf, format="PNG")
    backend = FakeBackend(images=[buf.getvalue()])

    result = asyncio.run(
        core.sheet("a slime", grid="4x2", backend=backend, out_dir=tmp_path, name="sheet")
    )
    assert len(result.frames) == 8
    assert all(p.exists() for p in result.frames)
    assert result.gif is not None and result.gif.exists()
    assert "4x2 grid" in backend.calls[0]["prompt"]


def test_sheet_rejects_a_bad_grid(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(core.sheet("x", grid="banana", backend=FakeBackend(), out_dir=tmp_path))
