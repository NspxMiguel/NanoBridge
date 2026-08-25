"""Canal principal: gemini.google.com com os cookies do navegador.

Por que este e não a API: a chave do AI Studio no plano gratuito tem cota zero
para os modelos de imagem (RESOURCE_EXHAUSTED já na primeira chamada), e ligar
faturamento passa a cobrar por imagem. A sessão web usa o plano do Gemini que a
conta já tem, com a cota que já está paga.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from ..errors import NoCookiesError, SessionExpiredError
from ..i18n import t
from .base import Backend, Result

_COOKIE_NAMES = ("__Secure-1PSID", "__Secure-1PSIDTS")
_BROWSERS = ("chrome", "brave", "edge", "chromium", "firefox", "safari")


def _from_env() -> dict[str, str] | None:
    psid = os.environ.get("NANOBRIDGE_1PSID") or os.environ.get("SECURE_1PSID")
    if not psid:
        return None
    psidts = os.environ.get("NANOBRIDGE_1PSIDTS") or os.environ.get("SECURE_1PSIDTS") or ""
    return {"__Secure-1PSID": psid, "__Secure-1PSIDTS": psidts, "_source": "env"}


def find_cookies() -> dict[str, str] | None:
    """Cookies do Gemini: variável de ambiente primeiro, depois cada navegador.

    Nunca devolve o valor para a tela — quem chama só usa para autenticar.
    """
    env = _from_env()
    if env:
        return env
    try:
        import browser_cookie3
    except ImportError:  # pragma: no cover - dependência declarada
        return None
    for name in _BROWSERS:
        loader = getattr(browser_cookie3, name, None)
        if loader is None:
            continue
        try:
            jar = loader(domain_name=".google.com")
        except Exception:
            # Navegador não instalado, perfil trancado, sem permissão — o
            # próximo da lista pode ter o cookie.
            continue
        found = {c.name: c.value for c in jar if c.name in _COOKIE_NAMES}
        if found.get("__Secure-1PSID"):
            found.setdefault("__Secure-1PSIDTS", "")
            found["_source"] = name
            return found
    return None


class WebBackend(Backend):
    name = "web"
    label = "Gemini web (cookies do navegador / browser cookies)"

    _client = None
    _lock = asyncio.Lock()

    def available(self) -> bool:
        return find_cookies() is not None

    def status(self) -> str:
        cookies = find_cookies()
        if not cookies:
            return t("doctor.cookies_missing")
        return t("doctor.cookies_found", browser=cookies.get("_source", "?"))

    async def _get_client(self):
        import gemini_webapi
        from gemini_webapi import GeminiClient

        # A biblioteca fala muito por padrão. No CLI isso polui a saída; no MCP,
        # qualquer linha solta atrapalha a leitura do que importa.
        if not os.environ.get("NANOBRIDGE_VERBOSE"):
            gemini_webapi.set_log_level("ERROR")

        async with WebBackend._lock:
            if WebBackend._client is not None:
                return WebBackend._client
            cookies = find_cookies()
            if not cookies:
                raise NoCookiesError()
            client = GeminiClient(cookies["__Secure-1PSID"], cookies.get("__Secure-1PSIDTS", ""))
            try:
                await client.init(timeout=120, auto_close=False, auto_refresh=True, verbose=False)
            except Exception as exc:  # sessão morta é o caso comum e tem conserto claro
                raise SessionExpiredError() from exc
            WebBackend._client = client
            return client

    async def quota(self) -> dict[str, str]:
        """Créditos restantes por modelo — é o número que diz se dá para insistir."""
        client = await self._get_client()
        raw = getattr(client, "quotas", None) or {}
        out: dict[str, str] = {}
        usage = raw.get("usage_info") or {}
        tier = (usage.get("tier") or {}).get("label")
        if tier:
            out["tier"] = str(tier)
        for window in ("current_5h", "weekly"):
            block = usage.get(window)
            if isinstance(block, dict) and block.get("remaining_credits") is not None:
                out[window] = t(
                    "doctor.used",
                    n=block["remaining_credits"],
                    pct=block.get("usage_percentage", "?"),
                )
        for key, value in raw.items():
            if not isinstance(value, dict) or "remaining" not in value:
                continue
            out[str(value.get("label") or key)] = f"{value['remaining']}/{value.get('total', '?')}"
        return out

    async def generate(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        model: str | None = None,
        conversation: str | None = None,
    ) -> Result:
        client = await self._get_client()
        chat = None
        if conversation:
            try:
                chat = client.start_chat(metadata=json.loads(conversation), model=model or None)
            except (json.JSONDecodeError, TypeError, ValueError):
                chat = None

        paths = [str(Path(f).expanduser()) for f in (files or [])]
        for p in paths:
            if not Path(p).exists():
                raise FileNotFoundError(t("err.file_missing", path=p))

        kwargs: dict[str, object] = {}
        if model:
            kwargs["model"] = model
        if chat is not None:
            output = await chat.send_message(prompt, files=paths or None, **kwargs)
            metadata = chat.metadata
        else:
            session = client.start_chat(**kwargs)
            output = await session.send_message(prompt, files=paths or None)
            metadata = session.metadata

        images: list[bytes] = []
        if output.images:
            # A biblioteca só sabe salvar em disco; um diretório temporário
            # transforma isso em bytes sem deixar lixo pelo caminho.
            with tempfile.TemporaryDirectory() as tmp:
                for index, image in enumerate(output.images):
                    saved = await image.save(path=tmp, filename=f"img_{index}", verbose=False)
                    images.append(Path(saved).read_bytes())

        return Result(
            images=images,
            text=output.text or "",
            backend=self.name,
            model=model or "gemini (nano banana)",
            conversation=json.dumps(metadata) if metadata else None,
        )

    async def close(self) -> None:
        client = WebBackend._client
        WebBackend._client = None
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
