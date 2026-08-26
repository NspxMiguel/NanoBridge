"""Textos de tela em português e inglês.

O idioma do sistema decide o padrão; NANOBRIDGE_LANG=pt|en força; a escolha do
usuário fica salva em ~/.config/nanobridge/config.json (ver config.py).
"""

from __future__ import annotations

import locale
import os

SUPPORTED = ("pt", "en")

STRINGS: dict[str, dict[str, str]] = {
    # --- doctor / backends
    "doctor.title": {
        "pt": "NanoBridge — diagnóstico",
        "en": "NanoBridge — diagnostics",
    },
    "doctor.backend": {"pt": "canal", "en": "backend"},
    "doctor.ready": {"pt": "pronto", "en": "ready"},
    "doctor.unavailable": {"pt": "indisponível", "en": "unavailable"},
    "doctor.cookies_found": {
        "pt": "cookies do Gemini encontrados no {browser}",
        "en": "Gemini cookies found in {browser}",
    },
    "doctor.cookies_missing": {
        "pt": (
            "nenhum cookie do Gemini no navegador — "
            "entre em gemini.google.com e tente de novo"
        ),
        "en": (
            "no Gemini cookies in the browser — "
            "sign in at gemini.google.com and retry"
        ),
    },
    "doctor.apikey_found": {
        "pt": "GEMINI_API_KEY presente (só funciona com faturamento ativo)",
        "en": "GEMINI_API_KEY present (only works with active billing)",
    },
    "doctor.apikey_missing": {
        "pt": "GEMINI_API_KEY ausente",
        "en": "GEMINI_API_KEY missing",
    },
    "doctor.quota": {"pt": "cota da conta", "en": "account quota"},
    "doctor.used": {"pt": "{n} créditos ({pct}% usado)", "en": "{n} credits ({pct}% used)"},
    "doctor.pillow_ok": {
        "pt": "pós-processamento de imagem disponível",
        "en": "image post-processing available",
    },
    "doctor.hint_none": {
        "pt": "Nenhum canal pronto. Abra gemini.google.com no Chrome, entre na conta e rode de novo.",
        "en": "No backend ready. Open gemini.google.com in Chrome, sign in, and run again.",
    },
    # --- geração
    "gen.working": {"pt": "gerando…", "en": "generating…"},
    "reset.done": {
        "pt": "sessão solta — a próxima chamada relê o cookie do navegador",
        "en": "session dropped — the next call rereads the browser cookie",
    },
    "reset.nothing": {
        "pt": "nenhuma sessão em memória — nada para soltar",
        "en": "no session in memory — nothing to drop",
    },
    "gen.saved": {"pt": "salvo em {path}", "en": "saved to {path}"},
    "gen.none": {
        "pt": "o modelo não devolveu imagem nenhuma. Resposta em texto: {text}",
        "en": "the model returned no image. Text response: {text}",
    },
    "gen.count": {"pt": "{n} imagem(ns)", "en": "{n} image(s)"},
    # --- erros
    "err.no_backend": {
        "pt": "nenhum canal disponível para falar com o Nano Banana",
        "en": "no backend available to reach Nano Banana",
    },
    "err.no_cookies": {
        "pt": "não achei os cookies do Gemini. Entre em https://gemini.google.com no Chrome e rode de novo.",
        "en": "could not find Gemini cookies. Sign in at https://gemini.google.com in Chrome and retry.",
    },
    "err.expired": {
        "pt": "a sessão do Gemini expirou. Abra https://gemini.google.com no Chrome para renovar.",
        "en": "the Gemini session expired. Open https://gemini.google.com in Chrome to refresh it.",
    },
    "err.file_missing": {"pt": "arquivo não encontrado: {path}", "en": "file not found: {path}"},
    "err.quota": {
        "pt": (
            "a API do Gemini recusou por cota: no plano gratuito os modelos de imagem têm cota "
            "zero, e só liberam com faturamento ativo (e aí cobram por imagem). "
            "O canal 'web' não tem esse problema — rode 'nanobridge doctor'."
        ),
        "en": (
            "the Gemini API refused on quota: on the free tier the image models have zero quota, "
            "and only unlock with active billing (which then charges per image). "
            "The 'web' backend does not have this problem — run 'nanobridge doctor'."
        ),
    },
    "err.backend": {
        "pt": "o canal {backend} recusou: {detail}",
        "en": "the {backend} backend refused: {detail}",
    },
    "err.bad_grid": {
        "pt": "grade inválida: use algo como 4x2",
        "en": "invalid grid: use something like 4x2",
    },
    # --- sprite / folha
    "sheet.sliced": {
        "pt": "folha cortada em {n} quadros ({cols}x{rows}) em {path}",
        "en": "sheet sliced into {n} frames ({cols}x{rows}) at {path}",
    },
    "sheet.gif": {"pt": "GIF montado: {path}", "en": "GIF assembled: {path}"},
    "tex.seam": {
        "pt": "emenda: horizontal {h}, vertical {v} (abaixo de {limit} ninguém vê)",
        "en": "seam: horizontal {h}, vertical {v} (under {limit} nobody sees it)",
    },
    "tex.repaired": {
        "pt": "emenda costurada: era {before}, ficou {after}",
        "en": "seam repaired: was {before}, now {after}",
    },
    "tex.clean": {"pt": "já repetia, não mexi", "en": "already tiled, left alone"},
    "cast.done": {
        "pt": "elenco com {n} sprites em {path}",
        "en": "cast of {n} sprites at {path}",
    },
    "cast.failed": {"pt": "não saiu: {subject} — {why}", "en": "did not come out: {subject} — {why}"},
    "cast.palette": {"pt": "paleta do elenco: {colours}", "en": "cast palette: {colours}"},
    "palette.list": {"pt": "paletas embutidas", "en": "built-in palettes"},
    "palette.extracted": {
        "pt": "{n} cores extraídas de {src}",
        "en": "{n} colours extracted from {src}",
    },
    "palette.saved": {"pt": "paleta salva em {path}", "en": "palette saved to {path}"},
    "palette.applied": {"pt": "paleta aplicada: {path}", "en": "palette applied: {path}"},
    "atlas.packed": {
        "pt": "atlas com {n} sprites em {path}, manifesto em {manifest}",
        "en": "atlas with {n} sprites at {path}, manifest at {manifest}",
    },
    # --- config
    "cfg.lang_set": {"pt": "idioma agora é {lang}", "en": "language is now {lang}"},
    "cfg.lang_bad": {
        "pt": "idioma desconhecido: {lang} (use pt ou en)",
        "en": "unknown language: {lang} (use pt or en)",
    },
    "cfg.path": {"pt": "configuração em {path}", "en": "configuration at {path}"},
}


def system_language() -> str:
    """pt quando o sistema estiver em português, en no resto."""
    for env in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env)
        if value:
            return "pt" if value.lower().startswith("pt") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except (ValueError, TypeError):  # pragma: no cover - depende do sistema
        loc = ""
    return "pt" if loc.lower().startswith("pt") else "en"


_forced: str | None = None


def set_language(lang: str) -> None:
    """Força o idioma no processo atual (usado pelo --lang e pelo config salvo)."""
    global _forced
    if lang not in SUPPORTED:
        raise ValueError(lang)
    _forced = lang


def current_language() -> str:
    """A variável de ambiente vence tudo — é como eu confiro tradução sem mexer na máquina dele."""
    forced_env = os.environ.get("NANOBRIDGE_LANG", "").strip().lower()[:2]
    if forced_env in SUPPORTED:
        return forced_env
    if _forced:
        return _forced
    return system_language()


def t(key: str, **kwargs: object) -> str:
    """Texto traduzido. Chave desconhecida volta como a própria chave — falha visível."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(current_language()) or entry.get("en") or key
    return text.format(**kwargs) if kwargs else text
