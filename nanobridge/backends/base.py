from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Result:
    """O que um canal devolve: bytes de imagem crus e o texto que veio junto."""

    images: list[bytes] = field(default_factory=list)
    text: str = ""
    backend: str = ""
    model: str = ""
    conversation: str | None = None  # para continuar editando a mesma imagem


class Backend:
    name = "base"
    label = "base"

    def available(self) -> bool:  # pragma: no cover - cada canal implementa
        raise NotImplementedError

    def status(self) -> str:
        """Uma linha, já traduzida, dizendo por que está (ou não) pronto."""
        raise NotImplementedError

    async def generate(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        model: str | None = None,
        conversation: str | None = None,
    ) -> Result:  # pragma: no cover - cada canal implementa
        raise NotImplementedError

    async def close(self) -> None:
        return None
