"""Canal de reserva: a API do AI Studio com GEMINI_API_KEY.

Só entra em cena quando a sessão web não existe. No plano gratuito a cota dos
modelos de imagem é zero — a chamada volta 429 RESOURCE_EXHAUSTED — então este
canal pressupõe faturamento ativo, e aí cada imagem é paga.
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

from ..i18n import t
from .base import Backend, Result

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3-pro-image"

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _key() -> str | None:
    """A chave vem do ambiente, ou do chaveiro do macOS via claude-autonomous.

    Nunca é impressa: só viaja daqui para o cabeçalho da requisição.
    """
    env = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if env:
        return env
    for service in ("claude-autonomous:GEMINI_API_KEY", "GEMINI_API_KEY"):
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-w"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        value = out.stdout.strip()
        if value:
            return value
    return None


class ApiBackend(Backend):
    name = "api"
    label = "Gemini API (GEMINI_API_KEY — precisa de faturamento / needs billing)"

    def available(self) -> bool:
        return _key() is not None

    def status(self) -> str:
        return t("doctor.apikey_found") if _key() else t("doctor.apikey_missing")

    async def generate(
        self,
        prompt: str,
        files: list[str | Path] | None = None,
        model: str | None = None,
        conversation: str | None = None,
    ) -> Result:
        import httpx

        key = _key()
        if not key:
            from ..errors import NoBackendError

            raise NoBackendError()

        parts: list[dict] = [{"text": prompt}]
        for f in files or []:
            path = Path(f).expanduser()
            if not path.exists():
                raise FileNotFoundError(t("err.file_missing", path=str(path)))
            parts.append(
                {
                    "inlineData": {
                        "mimeType": _MIME.get(path.suffix.lower(), "image/png"),
                        "data": base64.b64encode(path.read_bytes()).decode(),
                    }
                }
            )

        chosen = model or DEFAULT_MODEL
        async with httpx.AsyncClient(timeout=180) as http:
            response = await http.post(
                ENDPOINT.format(model=chosen),
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": parts}]},
            )
        payload = response.json()
        if "error" in payload:
            from ..errors import BackendError, QuotaError

            status = str(payload["error"].get("status") or response.status_code)
            if status == "RESOURCE_EXHAUSTED" or response.status_code == 429:
                # Não é "tente de novo mais tarde": no plano gratuito a cota de
                # imagem é zero e continua zero. Dizer isso poupa a espera.
                raise QuotaError()
            raise BackendError(self.name, f"{status}: {payload['error'].get('message', '')[:200]}")

        images: list[bytes] = []
        text = ""
        for candidate in payload.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "inlineData" in part:
                    images.append(base64.b64decode(part["inlineData"]["data"]))
                elif "text" in part:
                    text += part["text"]
        return Result(images=images, text=text, backend=self.name, model=chosen)
