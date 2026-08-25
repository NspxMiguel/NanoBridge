import asyncio
import io
import json

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


def test_safe_stem_cannot_escape_the_output_folder():
    """O `name` do MCP vem de um modelo: `../` não pode virar caminho de verdade."""
    assert core.safe_stem("../../etc/passwd") == "passwd"
    assert core.safe_stem("/absolute/thing.png") == "thing-png"
    assert core.safe_stem("..") == "nanobridge"
    assert "/" not in core.safe_stem("a/b/c")


def test_unique_path_never_overwrites(tmp_path):
    first = core.unique_path(tmp_path, "sprite", ".png")
    first.write_bytes(b"x")
    second = core.unique_path(tmp_path, "sprite", ".png")
    assert second.name == "sprite-2.png"
    second.write_bytes(b"x")
    assert core.unique_path(tmp_path, "sprite", ".png").name == "sprite-3.png"


def test_generating_the_same_subject_twice_keeps_both(tmp_path):
    backend = FakeBackend()
    a = asyncio.run(core.sprite("a slime", backend=backend, out_dir=tmp_path))
    b = asyncio.run(core.sprite("a slime", backend=backend, out_dir=tmp_path))
    assert a.paths[0] != b.paths[0]
    assert a.paths[0].exists() and b.paths[0].exists()


def test_name_with_traversal_stays_inside_out_dir(tmp_path):
    backend = FakeBackend()
    out = asyncio.run(core.generate("x", backend=backend, out_dir=tmp_path, name="../escaped"))
    assert out.paths[0].parent == tmp_path


def test_sheet_rerun_does_not_leave_stale_frames(tmp_path):
    """Grade menor na segunda rodada deixava quadros órfãos da primeira."""
    def sheet_bytes(cols):
        img = Image.new("RGB", (40 * cols, 40), (255, 255, 255))
        for c in range(cols):
            img.paste(Image.new("RGB", (20, 20), (10 + c * 30, 120, 40)), (c * 40 + 10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    first = asyncio.run(
        core.sheet("x", grid="4x1", backend=FakeBackend(images=[sheet_bytes(4)]), out_dir=tmp_path, name="s")
    )
    assert len(first.frames) == 4
    second = asyncio.run(
        core.sheet("x", grid="2x1", backend=FakeBackend(images=[sheet_bytes(2)]), out_dir=tmp_path, name="s")
    )
    assert len(second.frames) == 2
    on_disk = sorted(second.frames[0].parent.glob("*.png"))
    assert len(on_disk) == 2, f"sobraram quadros velhos: {[p.name for p in on_disk]}"


def test_build_atlas_writes_the_image_and_the_manifest(tmp_path):
    a = tmp_path / "hero.png"
    b = tmp_path / "villain.png"
    Image.new("RGBA", (30, 40), (255, 0, 0, 255)).save(a)
    Image.new("RGBA", (20, 20), (0, 0, 255, 255)).save(b)

    result = core.build_atlas([a, b], out_dir=tmp_path / "out")
    assert result.path.exists()
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["image"] == result.path.name
    names = {s["name"] for s in manifest["sprites"]}
    assert names == {"hero", "villain"}


def test_build_atlas_rejects_an_empty_list(tmp_path):
    with pytest.raises(ValueError):
        core.build_atlas([], out_dir=tmp_path)


def test_build_atlas_rejects_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        core.build_atlas([tmp_path / "nope.png"], out_dir=tmp_path)


def test_build_atlas_name_is_sanitised(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (1, 1, 1, 255)).save(src)
    result = core.build_atlas([src], out_dir=tmp_path / "out", name="../../escaped")
    assert result.path.parent == tmp_path / "out"
