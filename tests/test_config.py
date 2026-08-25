from nanobridge import config, i18n


def test_out_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOBRIDGE_OUT", str(tmp_path))
    assert config.default_out_dir() == tmp_path


def test_broken_config_does_not_break_the_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ não é json")
    assert config.load() == {}


def test_language_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("NANOBRIDGE_LANG", raising=False)
    config.set_language("pt")
    i18n._forced = None
    config.apply_saved_language()
    assert i18n.current_language() == "pt"
    i18n._forced = None
