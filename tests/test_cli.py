"""O CLI chamado como função: cobre o parser, o relatório e os comandos locais
sem subprocesso e sem rede, para que isso rode no CI junto com o resto."""

import io
import json

import pytest
from PIL import Image

from nanobridge import cli
from nanobridge.backends.base import Backend, Result


def png(size=(80, 80)) -> bytes:
    img = Image.new("RGB", size, (255, 255, 255))
    img.paste(Image.new("RGB", (30, 30), (10, 200, 40)), (25, 25))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sheet_bytes(cols, rows) -> bytes:
    img = Image.new("RGB", (40 * cols, 40 * rows), (255, 255, 255))
    for r in range(rows):
        for c in range(cols):
            img.paste(Image.new("RGB", (20, 20), (10 + c * 40, 120, 40)), (c * 40 + 10, r * 40 + 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, images=None):
        self.images = images if images is not None else [png()]
        self.calls = []

    def available(self):
        return True

    def status(self):
        return "fake"

    async def quota(self):
        return {"tier": "TEST"}

    async def generate(self, prompt, files=None, model=None, conversation=None):
        self.calls.append({"prompt": prompt, "files": files, "conversation": conversation})
        return Result(images=list(self.images), text="", backend=self.name, conversation="nb1_fake")

    async def close(self):
        return None


@pytest.fixture
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    monkeypatch.setattr("nanobridge.cli.pick", lambda preferred=None: backend)
    monkeypatch.setattr("nanobridge.cli.all_backends", lambda: [backend])
    # O CLI fecha o canal web no fim; sem isto o teste tocaria a rede.
    monkeypatch.setattr("nanobridge.backends.web.WebBackend.close", FakeBackend.close)
    return backend


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "in.png"
    path.write_bytes(png())
    return path


def test_version_and_help_exit_zero(capsys):
    for args in (["--version"], ["--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(args)
        assert exc.value.code == 0


def test_no_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_doctor_lists_backends_and_quota(fake, capsys):
    assert cli.main(["--lang", "en", "doctor"]) == 0
    out = capsys.readouterr().out
    assert "fake" in out
    assert "TEST" in out


def test_sprite_writes_a_file_and_prints_where(fake, tmp_path, capsys):
    assert cli.main(["--lang", "en", "sprite", "a slime", "--out", str(tmp_path), "--name", "s"]) == 0
    out = capsys.readouterr().out
    assert "saved to" in out
    assert (tmp_path / "s.png").exists()


def test_json_output_is_machine_readable(fake, tmp_path, capsys):
    assert cli.main(["gen", "a slime", "--out", str(tmp_path), "--name", "g", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "fake"
    assert payload["conversation"] == "nb1_fake"


def test_icon_and_edit_reach_the_backend(fake, tmp_path, image):
    assert cli.main(["icon", "a compass", "--out", str(tmp_path), "--name", "i"]) == 0
    assert cli.main(["edit", str(image), "make it blue", "--out", str(tmp_path), "--name", "e"]) == 0
    assert fake.calls[-1]["files"] == [image]


def test_sheet_slices_and_builds_a_gif(monkeypatch, tmp_path, capsys):
    backend = FakeBackend(images=[sheet_bytes(4, 2)])
    monkeypatch.setattr("nanobridge.core.pick", lambda preferred=None: backend)
    monkeypatch.setattr("nanobridge.backends.web.WebBackend.close", FakeBackend.close)
    assert cli.main(["--lang", "en", "sheet", "a slime", "--grid", "4x2",
                     "--out", str(tmp_path), "--name", "sh"]) == 0
    out = capsys.readouterr().out
    assert "8 frames (4x2)" in out
    assert "GIF" in out


def test_no_transparent_and_no_trim_flags_reach_core(fake, tmp_path):
    assert cli.main(["sprite", "a slime", "--no-transparent", "--no-trim",
                     "--out", str(tmp_path), "--name", "raw"]) == 0
    # sem pós-processamento o arquivo mantém o formato de origem
    assert (tmp_path / "raw.png").exists()


def test_cut_and_slice_need_no_backend(tmp_path, image, capsys):
    assert cli.main(["--lang", "en", "cut", str(image), "--size", "32",
                     "-o", str(tmp_path / "c.png")]) == 0
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(sheet_bytes(4, 1))
    assert cli.main(["--lang", "en", "slice", str(sheet), "--grid", "4x1",
                     "--out", str(tmp_path / "frames")]) == 0
    out = capsys.readouterr().out
    assert "4 frames (4x1)" in out
    assert (tmp_path / "frames" / "sheet.gif").exists()


def test_lang_command_persists_and_rejects_junk(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("NANOBRIDGE_LANG", raising=False)
    assert cli.main(["lang", "pt"]) == 0
    assert json.loads((tmp_path / "nanobridge" / "config.json").read_text())["lang"] == "pt"
    with pytest.raises(SystemExit):
        cli.main(["lang", "klingon"])


def test_missing_file_is_reported_not_raised(tmp_path, capsys):
    assert cli.main(["--lang", "en", "cut", str(tmp_path / "nope.png")]) == 2
    assert "not found" in capsys.readouterr().err


def test_open_never_breaks_the_command(fake, tmp_path, monkeypatch):
    """--open é conveniência: se o visualizador não existe, a imagem já foi salva."""
    def boom(*a, **k):
        raise OSError("no opener here")

    monkeypatch.setattr("nanobridge.cli.subprocess.run", boom)
    assert cli.main(["sprite", "a slime", "--out", str(tmp_path), "--name", "o", "--open"]) == 0
    assert (tmp_path / "o.png").exists()
