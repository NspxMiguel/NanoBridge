
import pytest

from nanobridge import i18n


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("NANOBRIDGE_LANG", raising=False)
    i18n._forced = None
    yield
    i18n._forced = None


def test_every_string_exists_in_both_languages():
    missing = [
        (key, lang)
        for key, entry in i18n.STRINGS.items()
        for lang in i18n.SUPPORTED
        if not entry.get(lang)
    ]
    assert missing == []


def test_env_var_wins_over_saved_choice(monkeypatch):
    i18n.set_language("en")
    monkeypatch.setenv("NANOBRIDGE_LANG", "pt")
    assert i18n.current_language() == "pt"


def test_set_language_rejects_unknown():
    with pytest.raises(ValueError):
        i18n.set_language("fr")


def test_placeholders_are_filled():
    i18n.set_language("pt")
    assert "/tmp/x.png" in i18n.t("gen.saved", path="/tmp/x.png")
    i18n.set_language("en")
    assert "/tmp/x.png" in i18n.t("gen.saved", path="/tmp/x.png")


def test_unknown_key_returns_key():
    assert i18n.t("nope.nope") == "nope.nope"


def test_system_locale_picks_portuguese(monkeypatch):
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    assert i18n.system_language() == "pt"
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.system_language() == "en"
