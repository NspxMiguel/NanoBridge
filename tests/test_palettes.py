"""Paletas: nomes embutidos, arquivos, listas, e o que o usuário digita errado."""


import pytest

from nanobridge import palettes


def test_every_builtin_parses_and_has_colours():
    for name in palettes.names():
        colours = palettes.resolve(name)
        assert colours, name
        assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in colours), name


def test_known_palettes_have_their_known_sizes():
    assert len(palettes.resolve("gameboy")) == 4
    assert len(palettes.resolve("pico8")) == 16
    assert len(palettes.resolve("endesga32")) == 32


@pytest.mark.parametrize(
    "value,expected",
    [("#FF0000", (255, 0, 0)), ("00ff00", (0, 255, 0)), ("#00F", (0, 0, 255))],
)
def test_hex_to_rgb(value, expected):
    assert palettes.hex_to_rgb(value) == expected


@pytest.mark.parametrize("bad", ["", "#12", "#12345", "nope", "#GGGGGG"])
def test_hex_to_rgb_rejects_junk(bad):
    with pytest.raises(ValueError):
        palettes.hex_to_rgb(bad)


def test_rgb_to_hex_round_trips():
    for colour in [(0, 0, 0), (255, 255, 255), (18, 52, 86)]:
        assert palettes.hex_to_rgb(palettes.rgb_to_hex(colour)) == colour


def test_resolve_accepts_a_comma_separated_list():
    assert palettes.resolve("#FF0000,#00FF00") == [(255, 0, 0), (0, 255, 0)]


def test_resolve_is_case_insensitive_for_names():
    assert palettes.resolve("PICO8") == palettes.resolve("pico8")


def test_resolve_reads_a_hex_file(tmp_path):
    path = tmp_path / "mine.hex"
    path.write_text("#112233\n; um comentário\n\n#445566\n")
    assert palettes.resolve(path) == [(17, 34, 51), (68, 85, 102)]


def test_resolve_rejects_an_unknown_name():
    with pytest.raises(ValueError) as err:
        palettes.resolve("nao-existe")
    assert "pico8" in str(err.value), "a mensagem tem que dizer o que existe"


def test_resolve_rejects_an_empty_file(tmp_path):
    path = tmp_path / "vazio.hex"
    path.write_text("; só comentário\n")
    with pytest.raises(ValueError):
        palettes.resolve(path)


def test_save_writes_something_resolve_reads_back(tmp_path):
    colours = [(1, 2, 3), (250, 251, 252)]
    saved = palettes.save(colours, tmp_path / "sub" / "p.hex")
    assert saved.exists()
    assert palettes.resolve(saved) == colours


def test_resolve_accepts_a_list_directly():
    assert palettes.resolve(["#010203"]) == [(1, 2, 3)]
