"""Configuração persistida — hoje só o idioma e a pasta de saída padrão."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import i18n


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "nanobridge"


def config_path() -> Path:
    return config_dir() / "config.json"


def default_out_dir() -> Path:
    env = os.environ.get("NANOBRIDGE_OUT")
    if env:
        return Path(env).expanduser()
    saved = load().get("out_dir")
    if saved:
        return Path(saved).expanduser()
    return Path.home() / "Pictures" / "NanoBridge"


def load() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        # Config corrompida não pode derrubar a ferramenta — o padrão volta a valer.
        return {}


def save(data: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def apply_saved_language() -> None:
    """Chamado no arranque: a escolha salva vale, a variável de ambiente vence."""
    lang = load().get("lang")
    if lang in i18n.SUPPORTED:
        i18n.set_language(lang)


def set_language(lang: str) -> Path:
    if lang not in i18n.SUPPORTED:
        raise ValueError(lang)
    data = load()
    data["lang"] = lang
    i18n.set_language(lang)
    return save(data)
