import pytest

from nanobridge import backends
from nanobridge.backends import api, web
from nanobridge.errors import NoBackendError


def test_web_comes_before_api():
    """A ordem é a regra de negócio: o plano já pago antes do que cobra."""
    assert [b.name for b in backends.all_backends()] == ["web", "api"]


def test_pick_skips_an_unavailable_backend(monkeypatch):
    monkeypatch.setattr(web.WebBackend, "available", lambda self: False)
    monkeypatch.setattr(api.ApiBackend, "available", lambda self: True)
    assert backends.pick().name == "api"


def test_pick_raises_when_nothing_is_available(monkeypatch):
    monkeypatch.setattr(web.WebBackend, "available", lambda self: False)
    monkeypatch.setattr(api.ApiBackend, "available", lambda self: False)
    with pytest.raises(NoBackendError):
        backends.pick()


def test_pick_honours_an_explicit_choice(monkeypatch):
    monkeypatch.setattr(web.WebBackend, "available", lambda self: True)
    monkeypatch.setattr(api.ApiBackend, "available", lambda self: True)
    assert backends.pick("api").name == "api"


def test_env_cookies_win_over_the_browser(monkeypatch):
    monkeypatch.setenv("NANOBRIDGE_1PSID", "abc")
    monkeypatch.setenv("NANOBRIDGE_1PSIDTS", "def")
    found = web.find_cookies()
    assert found["__Secure-1PSID"] == "abc"
    assert found["_source"] == "env"


def test_api_key_read_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert api._key() == "k"
