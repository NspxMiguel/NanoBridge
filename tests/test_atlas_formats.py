"""Cada formato de manifesto tem que ser lido pelo motor que ele promete."""

import json

import pytest

from nanobridge import atlas_formats as af
from nanobridge.imaging import AtlasEntry

ENTRIES = [AtlasEntry("hero", 0, 0, 32, 48), AtlasEntry("slime", 34, 0, 24, 24)]


def rendered(fmt: str) -> str:
    return af.render(fmt, ENTRIES, "atlas.png", 64, 48)


def test_every_declared_format_renders():
    for fmt in af.FORMATS:
        assert rendered(fmt).strip(), fmt


@pytest.mark.parametrize("fmt", ["nanobridge", "phaser", "texturepacker", "aseprite"])
def test_json_formats_are_valid_json(fmt):
    json.loads(rendered(fmt))


def test_nanobridge_format_keeps_the_flat_list():
    data = json.loads(rendered("nanobridge"))
    assert [s["name"] for s in data["sprites"]] == ["hero", "slime"]
    assert data["size"] == {"w": 64, "h": 48}


def test_texturepacker_hash_is_keyed_by_name():
    data = json.loads(rendered("texturepacker"))
    assert set(data["frames"]) == {"hero", "slime"}
    assert data["frames"]["hero"]["frame"] == {"x": 0, "y": 0, "w": 32, "h": 48}
    assert data["meta"]["size"] == {"w": 64, "h": 48}


def test_phaser_is_the_texturepacker_shape():
    assert rendered("phaser") == rendered("texturepacker")


def test_aseprite_frames_are_an_array_with_filenames():
    data = json.loads(rendered("aseprite"))
    assert isinstance(data["frames"], list)
    assert [f["filename"] for f in data["frames"]] == ["hero", "slime"]


def test_godot_declares_one_atlastexture_per_sprite():
    text = rendered("godot")
    assert text.startswith("[gd_resource")
    assert text.count('[sub_resource type="AtlasTexture"') == len(ENTRIES)
    assert "region = Rect2(0, 0, 32, 48)" in text
    assert 'path="atlas.png"' in text


def test_godot_load_steps_counts_the_resources():
    """load_steps errado faz o Godot recusar o arquivo."""
    text = rendered("godot")
    declared = int(text.split("load_steps=")[1].split()[0])
    assert declared == len(ENTRIES) + 2


def test_css_has_one_class_per_sprite_and_no_negative_zero():
    text = rendered("css")
    assert ".sprite--hero" in text and ".sprite--slime" in text
    assert "-0px" not in text
    assert "background-position: -34px 0px;" in text
    assert "image-rendering: pixelated" in text, "atlas de pixel art borrado não serve"


@pytest.mark.parametrize("fmt,suffix", [("godot", ".tres"), ("css", ".css"), ("phaser", ".json")])
def test_suffix_for(fmt, suffix):
    assert af.suffix_for(fmt) == suffix


def test_unknown_format_is_rejected_with_the_list():
    with pytest.raises(ValueError) as err:
        af.render("unreal", ENTRIES, "a.png", 1, 1)
    assert "godot" in str(err.value)
    with pytest.raises(ValueError):
        af.suffix_for("unreal")


def test_write_disambiguates_formats_that_share_a_suffix(tmp_path):
    """phaser e aseprite são os dois .json — um sobrescrevia o outro."""
    image = tmp_path / "a.png"
    image.write_bytes(b"")
    taken: set = set()
    first = af.write("nanobridge", ENTRIES, image, 64, 48, taken=taken)
    second = af.write("phaser", ENTRIES, image, 64, 48, taken=taken)
    third = af.write("aseprite", ENTRIES, image, 64, 48, taken=taken)
    assert len({first, second, third}) == 3
    assert first.name == "a.json"
    assert "phaser" in second.name and "aseprite" in third.name
