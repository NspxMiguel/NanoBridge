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


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _fake_http(payload, status=200):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return _Response(payload, status)

    return Client


def test_api_quota_error_is_readable_not_a_stack_trace(monkeypatch):
    """429 do plano gratuito e o caso comum: tem que virar mensagem, nao traceback."""
    import asyncio

    import httpx

    from nanobridge.errors import NanoBridgeError, QuotaError

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _fake_http({"error": {"status": "RESOURCE_EXHAUSTED", "message": "no quota"}}, 429)(),
    )
    with pytest.raises(QuotaError) as err:
        asyncio.run(api.ApiBackend().generate("x"))
    assert isinstance(err.value, NanoBridgeError)
    assert "billing" in str(err.value) or "faturamento" in str(err.value)


def test_api_other_errors_name_the_backend(monkeypatch):
    import asyncio

    import httpx

    from nanobridge.errors import BackendError

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _fake_http({"error": {"status": "INVALID_ARGUMENT", "message": "bad model"}}, 400)(),
    )
    with pytest.raises(BackendError) as err:
        asyncio.run(api.ApiBackend().generate("x"))
    assert "api" in str(err.value)
    assert "bad model" in str(err.value)
