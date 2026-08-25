"""As ferramentas MCP com um canal falso: é aqui que moraram os dois piores
defeitos (traceback vazando e resposta fora do formato), então elas precisam de
teste que não dependa de rede nem de cota."""

import io
import json

import pytest
from PIL import Image

from nanobridge import backends, mcp_server
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
