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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("You might be signed out or image creation may not be available.", True),
        ("Please sign in to continue.", True),
        ("Você parece estar desconectado.", True),
        ("I can't create that image — it goes against the policy.", False),
        ("Here you go!", False),
        ("", False),
    ],
)
def test_signed_out_detection(text, expected):
    """Sessão morta responde em texto, sem erro de rede: é o texto que denuncia."""
    assert web._sounds_signed_out(text) is expected


def test_expired_session_drops_the_shared_client(monkeypatch):
    """O servidor MCP vive dias: sem soltar o cliente, entrar de novo no Gemini
    não adiantaria nada até reiniciar o processo."""
    import asyncio

    from nanobridge.errors import SessionExpiredError

    class DeadOutput:
        images: list = []
        text = "You might be signed out or image creation may not be available."

    class FakeChat:
        metadata = ["c_1"]

        async def send_message(self, *a, **k):
            return DeadOutput()

    class FakeClient:
        quotas: dict = {}

        def start_chat(self, **kw):
            return FakeChat()

        async def close(self):
            return None

    backend = web.WebBackend()
    web.WebBackend._client = FakeClient()
    assert web.WebBackend._client is not None
    with pytest.raises(SessionExpiredError):
        asyncio.run(backend.generate("x"))
    assert web.WebBackend._client is None, "o cliente morto continuou em cache"


def test_cookie_file_override_is_passed_to_every_loader(monkeypatch):
    """NANOBRIDGE_COOKIE_FILE existe pra quem tem o navegador num lugar que o
    padrão de fábrica não acha — perfil de outro usuário, cópia de outra máquina."""
    monkeypatch.setenv("NANOBRIDGE_COOKIE_FILE", "/tmp/custom-cookies.sqlite")
    seen = []

    class FakeBrowserCookie3:
        def chrome(self, domain_name, cookie_file=None):
            seen.append(cookie_file)
            return []

    import sys

    monkeypatch.setitem(sys.modules, "browser_cookie3", FakeBrowserCookie3())
    web.find_cookies()
    assert seen == ["/tmp/custom-cookies.sqlite"]


@pytest.mark.asyncio
async def test_reset_drops_a_cached_client_and_reports_it():
    web.WebBackend._client = object()
    assert (await web.WebBackend().reset()) is True
    assert web.WebBackend._client is None


@pytest.mark.asyncio
async def test_reset_on_an_empty_cache_reports_nothing_to_drop():
    web.WebBackend._client = None
    assert (await web.WebBackend().reset()) is False


def test_debug_timing_never_touches_stdout(monkeypatch, capsys):
    """O MCP server fala JSON-RPC em stdout — uma linha de log ali quebra o
    protocolo. Isso já foi um bug real: _stage() usava print() puro."""
    monkeypatch.setattr(web, "_DEBUG_TIMING", True)
    web._stage("test stage", 0.0)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "test stage" in captured.err


@pytest.mark.parametrize(
    "quotas,esperado",
    [
        ({"None-11": {"remaining": 0, "total": 1200}}, True),
        ({"None-11": {"remaining": 850, "total": 1200}}, False),
        ({"usage_info": {"current_5h": {"remaining_credits": 0}}}, True),
        ({"usage_info": {"weekly": {"remaining_credits": 0}}}, True),
        ({"usage_info": {"current_5h": {"remaining_credits": 400}}}, False),
        ({}, False),
        ({"extra": {"default": {"is_blocked": False}}}, False),
    ],
)
def test_quota_exhaustion_is_read_from_the_number(quotas, esperado):
    """O modelo responde em prosa e nao fala de cota — quem sabe e o cliente,
    que ja tem o numero."""

    class FakeClient:
        pass

    c = FakeClient()
    c.quotas = quotas
    assert web._quota_exhausted(c) is esperado


@pytest.mark.asyncio
async def test_exhausted_quota_says_wait_not_sign_in_again():
    """Bug real: cota estourada saia como 'o modelo nao devolveu imagem', com o
    ERROR de cota so no log. A mensagem certa e que ela volta sozinha."""
    from nanobridge.errors import WebQuotaError

    class DeadOutput:
        images: list = []
        text = "I can't create more images for you today."

    class FakeChat:
        metadata = ["c_1"]

        async def send_message(self, *a, **k):
            return DeadOutput()

    class FakeClient:
        quotas = {"None-11": {"remaining": 0, "total": 1200}}

        def start_chat(self, **kw):
            return FakeChat()

        async def close(self):
            return None

    web.WebBackend._client = FakeClient()
    with pytest.raises(WebQuotaError) as err:
        await web.WebBackend().generate("x")
    assert "doctor" in str(err.value)
    web.WebBackend._client = None


@pytest.mark.asyncio
async def test_a_content_refusal_with_zero_quota_is_not_called_a_quota_error():
    """Medido nesta conta: uma geracao passou com a janela de 5h zerada. O numero
    sozinho nao prova nada, entao uma recusa de conteudo nao pode virar 'espere'."""
    from nanobridge.errors import NoImageError

    class Refusal:
        images: list = []
        text = "I can't generate that image because it goes against the policy."

    class FakeChat:
        metadata = ["c_1"]

        async def send_message(self, *a, **k):
            return Refusal()

    class FakeClient:
        quotas = {"None-11": {"remaining": 0, "total": 1200}}

        def start_chat(self, **kw):
            return FakeChat()

        async def close(self):
            return None

    web.WebBackend._client = FakeClient()
    from nanobridge import core

    with pytest.raises(NoImageError) as err:
        await core.generate("x", backend=web.WebBackend(), out_dir="/tmp")
    assert "policy" in str(err.value)
    web.WebBackend._client = None
