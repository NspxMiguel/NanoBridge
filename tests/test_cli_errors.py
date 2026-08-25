"""Nenhuma falha prevista pode sair como traceback — nem no CLI, nem no MCP."""

import subprocess
import sys
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "nanobridge"]
ROOT = Path(__file__).resolve().parents[1]


def run(*args, lang="en"):
    return subprocess.run(
        [*CLI, "--lang", lang, *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )


def sample(tmp_path):
    from PIL import Image

    path = tmp_path / "in.png"
    Image.new("RGB", (40, 40), (255, 255, 255)).save(path)
    return path


def test_missing_file_says_so(tmp_path):
    out = run("cut", str(tmp_path / "nope.png"))
    assert out.returncode == 2
    assert "Traceback" not in out.stderr + out.stdout
    assert "not found" in (out.stderr + out.stdout).lower()


def test_output_path_colliding_with_a_file(tmp_path):
    """`-o pasta/x.png` onde `pasta` é um arquivo: erro do sistema, não bug."""
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    out = run("cut", str(sample(tmp_path)), "-o", str(blocker / "x.png"))
    assert out.returncode == 2
    assert "Traceback" not in out.stderr + out.stdout
    assert "exists" in (out.stderr + out.stdout).lower()


def test_bad_grid_says_so(tmp_path):
    out = run("slice", str(sample(tmp_path)), "--grid", "banana")
    assert out.returncode == 2
    assert "Traceback" not in out.stderr + out.stdout


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_errors_are_translated(tmp_path, lang):
    out = run("cut", str(tmp_path / "nope.png"), lang=lang)
    body = (out.stderr + out.stdout).lower()
    assert ("não encontrado" in body) if lang == "pt" else ("not found" in body)
