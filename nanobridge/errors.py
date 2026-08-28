"""Erros que o CLI e o MCP sabem traduzir em mensagem útil."""

from __future__ import annotations

from .i18n import t


class NanoBridgeError(Exception):
    """Base — sempre carrega uma mensagem já traduzida."""


class NoBackendError(NanoBridgeError):
    def __init__(self) -> None:
        super().__init__(t("err.no_backend"))


class NoCookiesError(NanoBridgeError):
    def __init__(self) -> None:
        super().__init__(t("err.no_cookies"))


class SessionExpiredError(NanoBridgeError):
    def __init__(self) -> None:
        super().__init__(t("err.expired"))


class NoImageError(NanoBridgeError):
    def __init__(self, text: str = "") -> None:
        super().__init__(t("gen.none", text=(text or "—")[:300]))


class QuotaError(NanoBridgeError):
    """Cota estourada — o caso mais comum do canal api, e tem conserto conhecido."""

    def __init__(self) -> None:
        super().__init__(t("err.quota"))


class BackendError(NanoBridgeError):
    """Qualquer outra recusa do canal, já legível."""

    def __init__(self, backend: str, detail: str) -> None:
        super().__init__(t("err.backend", backend=backend, detail=detail))


class WebQuotaError(NanoBridgeError):
    """A cota do plano acabou — some sozinha com o tempo, e o usuário precisa
    saber que é isso e não um defeito."""

    def __init__(self) -> None:
        super().__init__(t("err.quota_web"))
