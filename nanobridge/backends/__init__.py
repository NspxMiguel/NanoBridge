"""Canais até o Nano Banana, do mais barato para o mais caro."""

from __future__ import annotations

from .base import Backend, Result
from .api import ApiBackend
from .web import WebBackend

#: Ordem de preferência. A web vem primeiro porque usa o plano que ele já paga;
#: a API só funciona com faturamento ativo e cobra por chamada.
BACKENDS: tuple[type[Backend], ...] = (WebBackend, ApiBackend)


def all_backends() -> list[Backend]:
    return [cls() for cls in BACKENDS]


def pick(preferred: str | None = None) -> Backend:
    """O canal escolhido, ou o primeiro que estiver pronto."""
    from ..errors import NoBackendError

    candidates = all_backends()
    if preferred:
        candidates = [b for b in candidates if b.name == preferred]
    for backend in candidates:
        if backend.available():
            return backend
    raise NoBackendError()


__all__ = ["Backend", "Result", "WebBackend", "ApiBackend", "all_backends", "pick", "BACKENDS"]
