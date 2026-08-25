import asyncio
import io
import json

import pytest
from conftest import opaque_colours
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


class FlakyBackend(FakeBackend):
    """Devolve texto nas primeiras `fail_times` chamadas, imagem depois."""

    def __init__(self, fail_times: int, text: str = "Sure, here is what X means:"):
        super().__init__()
        self.fail_times = fail_times
        self.fail_text = text
        self.prompts: list[str] = []

    async def generate(self, prompt, files=None, model=None, conversation=None):
        self.prompts.append(prompt)
        if len(self.prompts) <= self.fail_times:
            return Result(images=[], text=self.fail_text, backend=self.name)
        return Result(images=[png()], text="", backend=self.name, conversation="c1")


def test_a_text_reply_is_retried_with_a_nudge(tmp_path):
    """Foi o modo de falha mais comum na prática: o modelo responde conversa."""
    backend = FlakyBackend(fail_times=1)
    result = asyncio.run(core.generate("a slime", backend=backend, out_dir=tmp_path))
    assert result.paths, "a segunda tentativa tinha que ter salvo a imagem"
    assert len(backend.prompts) == 2
    assert backend.prompts[0] == "a slime"
    assert "not with text" in backend.prompts[1]
    assert backend.prompts[1].endswith("a slime")


def test_the_nudge_escalates_rather_than_repeating(tmp_path):
    backend = FlakyBackend(fail_times=2)
    asyncio.run(core.generate("a slime", backend=backend, out_dir=tmp_path))
    assert len(backend.prompts) == 3
    assert backend.prompts[1] != backend.prompts[2]
    assert "IMAGE REQUEST" in backend.prompts[2]


def test_retries_give_up_and_report_the_last_text(tmp_path):
    backend = FlakyBackend(fail_times=99, text="Here is a paragraph about slimes.")
    with pytest.raises(NoImageError) as err:
        asyncio.run(core.generate("a slime", backend=backend, out_dir=tmp_path, retries=2))
    assert len(backend.prompts) == 3
    assert "paragraph about slimes" in str(err.value)


def test_a_real_refusal_stops_immediately_instead_of_burning_quota(tmp_path):
    """Cada tentativa custa créditos do plano dele: insistir numa recusa é caro
    e inútil."""
    backend = FlakyBackend(fail_times=99, text="I can't create that image.")
    with pytest.raises(NoImageError):
        asyncio.run(core.generate("something", backend=backend, out_dir=tmp_path, retries=5))
    assert len(backend.prompts) == 1, "recusa não pode virar seis chamadas"


def test_retries_zero_means_one_attempt(tmp_path):
    backend = FlakyBackend(fail_times=99)
    with pytest.raises(NoImageError):
        asyncio.run(core.generate("a slime", backend=backend, out_dir=tmp_path, retries=0))
    assert len(backend.prompts) == 1


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I can't create that image.", True),
        ("That goes against the content policy.", True),
        ("Não posso criar essa imagem.", True),
        ("Here is your image!", False),
        ("The letter X has several meanings.", False),
        ("", False),
        # O modelo repete o pedido na resposta, então uma palavra comum na lista
        # de recusas desliga o retry justamente nos prompts normais. Um primeiro
        # rascunho tinha "against" e "policy" soltos e reprovava estes três:
        ("a knight leaning against a stone wall", False),
        ("an insurance policy document on a desk", False),
        ("two swords crossed against a shield", False),
        # A resposta real que motivou tudo isso — pergunta, não recusa:
        ("It looks like your message was just a single letter. How can I help?", False),
    ],
)
def test_refusal_detection(text, expected):
    assert core.looks_like_a_refusal(text) is expected


def test_a_retry_starts_a_fresh_conversation(tmp_path):
    """Uma conversa que já entendeu errado tende a insistir no erro."""
    backend = FlakyBackend(fail_times=1)
    seen = []

    original = backend.generate

    async def spy(prompt, files=None, model=None, conversation=None):
        seen.append(conversation)
        return await original(prompt, files=files, model=model, conversation=conversation)

    backend.generate = spy
    asyncio.run(core.generate("a slime", backend=backend, out_dir=tmp_path, conversation="nb1_old"))
    assert seen[0] == "nb1_old"
    assert seen[1] is None


def test_generate_with_a_palette_locks_the_colours(tmp_path):
    backend = FakeBackend()
    result = asyncio.run(
        core.generate("x", backend=backend, out_dir=tmp_path, name="p", palette="gameboy")
    )
    with Image.open(result.paths[0]) as img:
        used = opaque_colours(img)
    allowed = set(core.palettes.resolve("gameboy"))
    assert used <= allowed, used - allowed


def test_a_bad_palette_fails_before_writing_anything(tmp_path):
    """Nome errado tem que falhar de cara, não depois de gravar meia dúzia."""
    backend = FakeBackend()
    with pytest.raises(ValueError):
        asyncio.run(core.generate("x", backend=backend, out_dir=tmp_path, palette="nao-existe"))
    assert not list(tmp_path.glob("*.png"))


def test_palette_from_image_round_trips_through_apply(tmp_path):
    src = tmp_path / "src.png"
    Image.open(io.BytesIO(png())).save(src)
    colours = core.palette_from_image(src, count=4)
    assert colours

    other = tmp_path / "other.png"
    Image.new("RGBA", (20, 20), (10, 200, 250, 255)).save(other)
    out = core.apply_palette(other, [core.palettes.rgb_to_hex(c) for c in colours], out=tmp_path / "o.png")
    with Image.open(out) as img:
        used = opaque_colours(img)
    assert used <= set(colours)


def test_apply_palette_defaults_to_a_sibling_file(tmp_path):
    src = tmp_path / "hero.png"
    Image.open(io.BytesIO(png())).save(src)
    out = core.apply_palette(src, "gameboy")
    assert out.name == "hero-palette.png"
    assert out.parent == tmp_path


def test_apply_palette_rejects_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        core.apply_palette(tmp_path / "nope.png", "gameboy")
