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


class Mesh3DUnavailableError(NanoBridgeError):
    """Falta a dependência opcional de 3D. Ela é opcional de propósito: quem só
    quer sprite 2D não deve ser obrigado a baixar NumPy, trimesh e afins."""

    def __init__(self, missing: str = "") -> None:
        super().__init__(t("err.mesh_deps", missing=missing or "trimesh"))


class EmptyMeshError(NanoBridgeError):
    def __init__(self, path: str = "") -> None:
        super().__init__(t("err.mesh_empty", path=path))


class MeshBackendError(NanoBridgeError):
    """O gerador 3D recusou. Diferente do canal de imagem, aqui existe uma fila
    pública do outro lado: dizer qual motor falhou é o que permite trocar."""

    def __init__(self, engine: str, detail: str) -> None:
        super().__init__(t("err.mesh_backend", engine=engine, detail=detail))


class NoMeshEngineError(NanoBridgeError):
    def __init__(self) -> None:
        super().__init__(t("err.mesh_no_engine"))


class BlenderMissingError(NanoBridgeError):
    """Sem Blender não há refino. É dependência externa de propósito: são 400 MB,
    e quem só quer sprite 2D não pode ser obrigado a baixar isso."""

    def __init__(self) -> None:
        super().__init__(t("err.blender_missing"))


class BlenderError(NanoBridgeError):
    def __init__(self, detail: str) -> None:
        super().__init__(t("err.blender", detail=detail))
