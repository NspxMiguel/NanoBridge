"""As ferramentas MCP com um canal falso: é aqui que moraram os dois piores
defeitos (traceback vazando e resposta fora do formato), então elas precisam de
teste que não dependa de rede nem de cota."""

import io
import json
from pathlib import Path

import pytest
from conftest import opaque_colours
from PIL import Image

from nanobridge import backends, core, mcp_server
from nanobridge.backends.base import Backend, Result
from nanobridge.errors import SessionExpiredError

try:
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover - mcp 1.x
    from mcp.server.fastmcp.exceptions import ToolError


def png(size=(80, 80)):
    img = Image.new("RGB", size, (255, 255, 255))
    img.paste(Image.new("RGB", (30, 30), (10, 200, 40)), (25, 25))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sheet_png(cols, rows):
    img = Image.new("RGB", (40 * cols, 40 * rows), (255, 255, 255))
    for r in range(rows):
        for c in range(cols):
            img.paste(Image.new("RGB", (20, 20), (10 + c * 40, 120, 40)), (c * 40 + 10, r * 40 + 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, images=None, raises=None, text=""):
        self.images = images if images is not None else [png()]
        self.raises = raises
        self.text = text
        self.calls = []

    def available(self):
        return True

    def status(self):
        return "fake"

    async def generate(self, prompt, files=None, model=None, conversation=None):
        self.calls.append({"prompt": prompt, "files": files, "conversation": conversation})
        if self.raises:
            raise self.raises
        return Result(images=list(self.images), text=self.text, backend=self.name, conversation="nb1_fake")


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(backends, "pick", lambda preferred=None: backend)
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    return backend


def payload(parts):
    return json.loads(next(p.text for p in parts if getattr(p, "type", "") == "text"))


def images(parts):
    return [p for p in parts if getattr(p, "type", "") == "image"]


@pytest.mark.asyncio
async def test_generate_sprite_returns_json_and_the_picture(fake, tmp_path):
    parts = await mcp_server.generate_sprite("a slime", out_dir=str(tmp_path), name="s")
    data = payload(parts)
    assert data["paths"] and data["backend"] == "fake"
    assert data["conversation"] == "nb1_fake"
    assert images(parts), "o agente precisa ver o que desenhou"


@pytest.mark.asyncio
async def test_generate_sprite_sheet_reports_the_grid_as_a_field(monkeypatch, tmp_path):
    backend = FakeBackend(images=[sheet_png(4, 2)])
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    parts = await mcp_server.generate_sprite_sheet("a slime", grid="4x2", out_dir=str(tmp_path), name="sh")
    data = payload(parts)
    assert data["grid"] == "4x2"
    assert len(data["frames"]) == 8
    assert data["gif"]


@pytest.mark.asyncio
async def test_expired_session_reaches_the_model_as_a_message(monkeypatch, tmp_path):
    backend = FakeBackend(raises=SessionExpiredError())
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    with pytest.raises(ToolError) as err:
        await mcp_server.generate_sprite("a slime", out_dir=str(tmp_path))
    assert "gemini.google.com" in str(err.value)


@pytest.mark.asyncio
async def test_a_refusal_reaches_the_model_with_the_models_own_words(monkeypatch, tmp_path):
    backend = FakeBackend(images=[], text="I can't draw that.")
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    with pytest.raises(ToolError) as err:
        await mcp_server.generate_image("x", out_dir=str(tmp_path))
    assert "can't draw" in str(err.value)


@pytest.mark.asyncio
async def test_edit_image_checks_the_file_before_spending_quota(fake, tmp_path):
    with pytest.raises(ToolError) as err:
        await mcp_server.edit_image(str(tmp_path / "nope.png"), "make it blue")
    assert "not found" in str(err.value) or "não encontrado" in str(err.value)
    assert fake.calls == [], "não pode ter chamado o modelo"


def test_cut_image_missing_file_is_a_message(tmp_path):
    with pytest.raises(ToolError):
        mcp_server.cut_image(str(tmp_path / "nope.png"))


def test_slice_sheet_bad_grid_is_a_message(tmp_path):
    path = tmp_path / "x.png"
    Image.open(io.BytesIO(png())).save(path)
    with pytest.raises(ToolError):
        mcp_server.slice_sheet(str(path), grid="banana")


@pytest.mark.asyncio
async def test_name_from_the_model_cannot_escape_out_dir(fake, tmp_path):
    parts = await mcp_server.generate_sprite("a slime", out_dir=str(tmp_path), name="../../escaped")
    assert all(str(tmp_path) in p for p in payload(parts)["paths"])


@pytest.mark.asyncio
async def test_nanobridge_reset_reports_whether_anything_dropped():
    from nanobridge.backends.web import WebBackend

    WebBackend._client = None
    assert "nothing" in (await mcp_server.nanobridge_reset()).lower()

    WebBackend._client = object()
    assert "dropped" in (await mcp_server.nanobridge_reset()).lower()
    assert WebBackend._client is None


def test_pack_atlas_returns_the_manifest_and_a_preview(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.open(io.BytesIO(png())).save(a)
    Image.open(io.BytesIO(png())).resize((40, 40)).save(b)
    out = tmp_path / "out"
    parts = mcp_server.pack_atlas([str(a), str(b)], out_dir=str(out))
    data = payload(parts)
    assert len(data["sprites"]) == 2
    assert images(parts)


def test_pack_atlas_missing_file_is_a_message(tmp_path):
    with pytest.raises(ToolError):
        mcp_server.pack_atlas([str(tmp_path / "nope.png")])


def test_pack_atlas_empty_list_is_a_message():
    with pytest.raises(ToolError):
        mcp_server.pack_atlas([])


def test_list_palettes_names_the_builtins_and_the_other_forms():
    text = mcp_server.list_palettes()
    assert "pico8" in text and "gameboy" in text
    assert ".hex" in text, "o agente precisa saber que aceita arquivo e lista"


def test_extract_palette_tool_returns_hex_and_can_save(tmp_path):
    src = tmp_path / "s.png"
    Image.open(io.BytesIO(png())).save(src)
    dest = tmp_path / "p.hex"
    data = json.loads(mcp_server.extract_palette(str(src), count=4, out=str(dest)))
    assert data["count"] == len(data["colours"]) <= 4
    assert all(c.startswith("#") for c in data["colours"])
    assert dest.exists()


def test_apply_palette_tool_rewrites_and_previews(tmp_path):
    src = tmp_path / "s.png"
    Image.new("RGBA", (20, 20), (200, 30, 30, 255)).save(src)
    out = tmp_path / "o.png"
    parts = mcp_server.apply_palette(str(src), "gameboy", out=str(out))
    assert json.loads(next(p.text for p in parts if getattr(p, "type", "") == "text"))["path"]
    assert images(parts)
    with Image.open(out) as img:
        assert opaque_colours(img) <= set(mcp_server.palettes.resolve("gameboy"))


def test_apply_palette_tool_unknown_palette_is_a_message(tmp_path):
    src = tmp_path / "s.png"
    Image.open(io.BytesIO(png())).save(src)
    with pytest.raises(ToolError):
        mcp_server.apply_palette(str(src), "nao-existe")


@pytest.mark.asyncio
async def test_generate_sprite_accepts_a_palette(fake, tmp_path):
    parts = await mcp_server.generate_sprite("a slime", out_dir=str(tmp_path), name="s", palette="gameboy")
    path = payload(parts)["paths"][0]
    with Image.open(path) as img:
        assert opaque_colours(img) <= set(mcp_server.palettes.resolve("gameboy"))


@pytest.mark.asyncio
async def test_generate_icon_returns_json_and_the_picture(fake, tmp_path):
    parts = await mcp_server.generate_icon("a coin", out_dir=str(tmp_path))
    data = payload(parts)
    assert data["paths"] and data["backend"] == "fake"
    assert images(parts), "the agent needs to see what it drew"


@pytest.mark.asyncio
async def test_generate_cast_builds_an_atlas_from_the_group(fake, tmp_path):
    parts = await mcp_server.generate_cast(["a slime", "a knight"], out_dir=str(tmp_path))
    data = payload(parts)
    assert len(data["sprites"]) == 2
    assert data["atlas"]
    assert data["failed"] == {}
    assert images(parts), "the atlas preview has to come back too"


@pytest.mark.asyncio
async def test_generate_cast_keeps_the_others_when_one_subject_fails(monkeypatch, tmp_path):
    calls = {"n": 0}

    class FlakyBackend(FakeBackend):
        async def generate(self, prompt, files=None, model=None, conversation=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SessionExpiredError()
            return await super().generate(prompt, files=files, model=model, conversation=conversation)

    backend = FlakyBackend()
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    parts = await mcp_server.generate_cast(["a slime", "a knight"], out_dir=str(tmp_path))
    data = payload(parts)
    assert len(data["sprites"]) == 1
    assert len(data["failed"]) == 1


@pytest.mark.asyncio
async def test_generate_variations_returns_a_contact_sheet(fake, tmp_path):
    parts = await mcp_server.generate_variations("a slime", count=3, out_dir=str(tmp_path))
    data = payload(parts)
    assert len(data["paths"]) == 3
    assert data["contact_sheet"]
    assert data["failed"] == []
    assert images(parts)


@pytest.mark.asyncio
async def test_generate_texture_reports_the_seam(fake, tmp_path):
    parts = await mcp_server.generate_texture("bricks", out_dir=str(tmp_path))
    data = payload(parts)
    assert data["path"]
    assert "seam" in data and "seam_before" in data
    assert data["threshold"] == core.SEAM_THRESHOLD
    assert images(parts)


@pytest.mark.asyncio
async def test_animate_sprite_keeps_the_reference_image(monkeypatch, tmp_path):
    reference = tmp_path / "knight.png"
    Image.open(io.BytesIO(png())).save(reference)
    backend = FakeBackend(images=[sheet_png(4, 1)])
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)

    parts = await mcp_server.animate_sprite(str(reference), out_dir=str(tmp_path))

    data = payload(parts)
    assert len(data["frames"]) == 4
    assert backend.calls[0]["files"], "the existing sprite has to go along as reference"


@pytest.mark.asyncio
async def test_nanobridge_status_lists_backends_and_styles(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(mcp_server, "all_backends", lambda: [backend])
    monkeypatch.setattr(mcp_server, "pick", lambda preferred=None: backend)

    report = await mcp_server.nanobridge_status()

    assert "fake: ready — fake" in report
    assert "chosen: fake" in report
    assert "styles:" in report


def test_list_atlas_formats_names_every_engine_shape():
    data = json.loads(mcp_server.list_atlas_formats())
    assert {"nanobridge", "phaser", "godot", "css", "aseprite"} <= data.keys()


def test_list_mesh_engines_lists_the_available_engines():
    from nanobridge import mesh3d

    data = json.loads(mcp_server.list_mesh_engines())
    assert [e["name"] for e in data] == [e.name for e in mesh3d.ENGINES]
    assert all("license" in e and "space" in e for e in data)


def test_blender_status_reports_whether_blender_was_found(monkeypatch):
    monkeypatch.setattr("nanobridge.blender.find_blender", lambda: "/opt/blender/blender")
    monkeypatch.setattr("nanobridge.blender.version", lambda: "4.2.0")
    data = json.loads(mcp_server.blender_status())
    assert data == {"found": "/opt/blender/blender", "version": "4.2.0"}


def test_build_normal_map_derives_a_map_from_a_sprite(tmp_path):
    src = tmp_path / "sprite.png"
    Image.open(io.BytesIO(png())).save(src)
    out = tmp_path / "sprite-normal.png"

    parts = mcp_server.build_normal_map(str(src), out=str(out))

    data = json.loads(parts[0].text)
    assert data["path"] == str(out)
    assert out.exists()
    assert images(parts)


def test_generate_mesh_wraps_the_reconstruction_result(monkeypatch, tmp_path):
    mesh_path = tmp_path / "m.glb"

    def fake_mesh_from_image(image, *, out_dir=None, name=None, engine=None, **kwargs):
        assert image == "ref.png"
        return core.Mesh3D(
            path=mesh_path,
            engine="tripo-sr",
            engine_label="TripoSR",
            license="MIT",
            source_image=Path("ref.png"),
            stats={"vertices": 10, "faces": 8, "depth_ratio": 0.4, "watertight": True},
        )

    monkeypatch.setattr(core, "mesh_from_image", fake_mesh_from_image)

    parts = mcp_server.generate_mesh("ref.png", out_dir=str(tmp_path))

    data = json.loads(parts[0].text)
    assert data["mesh"] == str(mesh_path)
    assert data["engine"] == "tripo-sr"
    assert "warning" not in data
    # previews=0 for a bare mesh: nothing to show yet, only the render tools draw frames.
    assert len(parts) == 1


@pytest.mark.asyncio
async def test_generate_sprite_3d_wraps_the_full_pipeline_result(monkeypatch, tmp_path):
    mesh_path = tmp_path / "m.glb"

    async def fake_sprite_3d(subject, **kwargs):
        return core.Mesh3D(
            path=mesh_path,
            engine="tripo-sr",
            engine_label="TripoSR",
            license="MIT",
            stats={"depth_ratio": 0.4},
        )

    monkeypatch.setattr(core, "sprite_3d", fake_sprite_3d)

    parts = await mcp_server.generate_sprite_3d("a round mushroom enemy")

    data = json.loads(parts[0].text)
    assert data["mesh"] == str(mesh_path)
    assert data["engine_label"] == "TripoSR"


@pytest.mark.asyncio
async def test_generate_model_3d_wraps_the_refined_result(monkeypatch, tmp_path):
    output = tmp_path / "chest.glb"

    async def fake_model_3d(subject, **kwargs):
        return core.Model3D(
            reference=tmp_path / "ref.png",
            raw_mesh=tmp_path / "raw.glb",
            engine="tripo-sr",
            engine_label="TripoSR",
            license="MIT",
            refined=core.Refined(
                outputs=[output],
                texture=tmp_path / "chest-albedo.png",
                before={"faces": 200000},
                after={"faces": 6000, "quad_ratio": 1.0},
                retopo=True,
                uv_created=True,
            ),
        )

    monkeypatch.setattr(core, "model_3d", fake_model_3d)

    parts = await mcp_server.generate_model_3d("a wooden treasure chest")

    data = json.loads(parts[0].text)
    assert data["outputs"] == [str(output)]
    assert data["engine_label"] == "TripoSR"
    assert data["raw_mesh"] == str(tmp_path / "raw.glb")
