"""O contrato de resposta do servidor MCP: um bloco de texto, sempre JSON puro."""

import json
from pathlib import Path

import pytest
from PIL import Image

from nanobridge import core, mcp_server


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGBA", (20, 20), (10, 20, 30, 255)).save(path)
    return path


def test_respond_is_pure_json(image):
    result = core.Generated(paths=[image], backend="fake", conversation="nb1_x")
    payload = json.loads(mcp_server._respond(result)[0].text)
    assert payload["paths"] == [str(image)]
    assert payload["conversation"] == "nb1_x"
    assert "grid" not in payload


def test_grid_is_a_field_not_a_prefix(image):
    """Antes vinha 'grid=4x2\\n{json}', e quem lia precisava saber a ferramenta."""
    result = core.Generated(paths=[image], grid=(4, 2))
    text = mcp_server._respond(result)[0].text
    assert not text.startswith("grid=")
    assert json.loads(text)["grid"] == "4x2"


def test_respond_hands_the_image_back_to_the_model(image):
    parts = mcp_server._respond(core.Generated(paths=[image]))
    assert any(getattr(p, "type", "") == "image" for p in parts)


def test_preview_is_capped(tmp_path):
    """Imagem grande de volta ao modelo enche a janela de contexto sem ajudar."""
    big = tmp_path / "big.png"
    Image.new("RGBA", (2000, 1200), (0, 0, 0, 255)).save(big)
    content = mcp_server._preview(big)
    import base64
    import io

    with Image.open(io.BytesIO(base64.b64decode(content.data))) as out:
        assert max(out.size) <= mcp_server.PREVIEW_MAX_SIDE


def test_every_tool_is_wrapped_against_leaking_tracebacks():
    """Ferramenta nova sem @handled volta a vazar pilha pro modelo."""
    source = Path(mcp_server.__file__).read_text()
    decorated = source.count("@mcp.tool()\n@handled\n")
    declared = source.count("@mcp.tool()")
    assert decorated == declared, f"{declared - decorated} ferramenta(s) sem @handled"
