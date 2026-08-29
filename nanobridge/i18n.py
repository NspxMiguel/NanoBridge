"""Textos de tela em português e inglês.

O idioma do sistema decide o padrão; NANOBRIDGE_LANG=pt|en força; a escolha do
usuário fica salva em ~/.config/nanobridge/config.json (ver config.py).
"""

from __future__ import annotations

import locale
import os

SUPPORTED = ("pt", "en")

STRINGS: dict[str, dict[str, str]] = {
    "model.stage_reference": {
        "pt": "1/4 desenhando a referência no Nano Banana…",
        "en": "1/4 drawing the reference in Nano Banana…",
    },
    "model.stage_refine": {
        "pt": "3/4 refinando no Blender: quadriláteros, UV e textura…",
        "en": "3/4 refining in Blender: quads, UV and texture…",
    },
    "model.stage_render": {"pt": "4/4 renderizando o retrato…", "en": "4/4 rendering the preview…"},
    "blender.opening": {"pt": "abrindo {path} no Blender", "en": "opening {path} in Blender"},
    # --- Blender
    "err.blender_missing": {
        "pt": "o Blender não está instalado — `brew install --cask blender`, ou aponte "
              "NANOBRIDGE_BLENDER para o executável",
        "en": "Blender is not installed — `brew install --cask blender`, or point "
              "NANOBRIDGE_BLENDER at the executable",
    },
    "err.blender": {"pt": "o Blender recusou: {detail}", "en": "Blender refused: {detail}"},
    "refine.done": {
        "pt": "{before_faces} faces → {after_faces} ({quad_ratio:.0%} quadriláteros), "
              "UV {uv}, textura {texture}",
        "en": "{before_faces} faces → {after_faces} ({quad_ratio:.0%} quads), UV {uv}, texture {texture}",
    },
    "refine.uv_new": {"pt": "criada", "en": "created"},
    "refine.uv_kept": {"pt": "a que já tinha", "en": "kept"},
    "refine.no_color": {
        "pt": "a malha não trazia cor nenhuma — saiu sem textura, só geometria",
        "en": "the mesh carried no colour — it came out untextured, geometry only",
    },
    # --- 3D (comandos)
    "mesh3d.stage_reference": {
        "pt": "1/3 desenhando a referência no Nano Banana…",
        "en": "1/3 drawing the reference in Nano Banana…",
    },
    "mesh3d.stage_engine": {
        "pt": "2/3 reconstruindo em 3D com {engine}…",
        "en": "2/3 reconstructing in 3D with {engine}…",
    },
    "mesh3d.made_by": {
        "pt": "malha feita por {engine} — licença {license}",
        "en": "mesh made by {engine} — {license} licence",
    },
    "mesh3d.stats": {
        "pt": "{vertices} vértices, {faces} faces, proporção de profundidade {depth_ratio}",
        "en": "{vertices} vertices, {faces} faces, depth ratio {depth_ratio}",
    },
    "mesh3d.flat_warning": {
        "pt": "aviso: quase sem profundidade — a referência provavelmente era arte 2D chapada; "
              "peça um render 3D de um objeto só, de frente, em fundo liso",
        "en": "warning: almost no depth — the reference was probably flat 2D art; "
              "ask for a 3D render of a single object, facing the camera, on a plain background",
    },
    "mesh3d.engines": {"pt": "motores 3D", "en": "3D engines"},
    # --- 3D (malha e render)
    "err.mesh_deps": {
        "pt": "falta a parte 3D: instale com  pip install 'nanobridge[3d]'  (faltou {missing})",
        "en": "3D support is missing: install it with  pip install 'nanobridge[3d]'  (missing {missing})",
    },
    "err.mesh_empty": {
        "pt": "a malha em {path} não tem face nenhuma",
        "en": "the mesh at {path} has no faces",
    },
    "err.mesh_backend": {
        "pt": "o motor 3D {engine} recusou: {detail}",
        "en": "the 3D engine {engine} refused: {detail}",
    },
    "err.mesh_no_engine": {
        "pt": "nenhum motor 3D respondeu — todos os espaços públicos estão fora do ar agora",
        "en": "no 3D engine answered — every public space is down right now",
    },
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
    "setup.title": {"pt": "NanoBridge — primeiro uso", "en": "NanoBridge — first run"},
    "setup.no_login": {
        "pt": (
            "Não existe login aqui, e não existe chave para colar.\n"
            "  O NanoBridge lê o cookie de sessão do Gemini que já está no seu\n"
            "  navegador. Se você consegue abrir gemini.google.com e conversar,\n"
            "  ele consegue gerar imagem — é literalmente a mesma sessão."
        ),
        "en": (
            "There is no login here, and no key to paste.\n"
            "  NanoBridge reads the Gemini session cookie already in your\n"
            "  browser. If you can open gemini.google.com and chat, it can\n"
            "  generate images — it is literally the same session."
        ),
    },
    "setup.step": {"pt": "{n}. {what}", "en": "{n}. {what}"},
    "setup.checking_cookies": {
        "pt": "procurando a sessão no navegador",
        "en": "looking for the browser session",
    },
    "setup.found": {"pt": "achei no {browser}", "en": "found in {browser}"},
    "setup.not_found": {
        "pt": (
            "não achei sessão nenhuma.\n"
            "     Abra https://gemini.google.com no Chrome, entre na sua conta\n"
            "     Google, mande uma mensagem qualquer, e rode isto de novo."
        ),
        "en": (
            "no session found.\n"
            "     Open https://gemini.google.com in Chrome, sign in to your\n"
            "     Google account, send any message, then run this again."
        ),
    },
    "setup.opening": {
        "pt": "abrindo o Gemini no navegador para você entrar…",
        "en": "opening Gemini in your browser so you can sign in…",
    },
    "setup.checking_session": {"pt": "conferindo se a sessão vale", "en": "checking the session is live"},
    "setup.session_ok": {"pt": "sessão boa, plano {tier}", "en": "session live, {tier} plan"},
    "setup.generating": {
        "pt": "gerando uma imagem de teste (leva uns 30s)",
        "en": "generating one test image (about 30s)",
    },
    "setup.generated": {"pt": "saiu: {path}", "en": "came out: {path}"},
    "setup.mcp_ok": {
        "pt": "servidor MCP registrado no Claude Code",
        "en": "MCP server registered with Claude Code",
    },
    "setup.mcp_missing": {
        "pt": "MCP não registrado. Rode: claude mcp add nanobridge --scope user -- {bin} mcp",
        "en": "MCP not registered. Run: claude mcp add nanobridge --scope user -- {bin} mcp",
    },
    "setup.ready": {
        "pt": "Tudo pronto. Experimente: nanobridge sprite \"um slime verde\"",
        "en": "All set. Try: nanobridge sprite \"a green slime\"",
    },
    "setup.not_ready": {
        "pt": "Faltou o passo acima. Resolva e rode 'nanobridge setup' de novo.",
        "en": "The step above is missing. Fix it and run 'nanobridge setup' again.",
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
    "err.quota_web": {
        "pt": (
            "a cota do seu plano Gemini acabou nesta janela. "
            "Ela volta sozinha — 'nanobridge doctor' mostra quanto falta e quando reseta."
        ),
        "en": (
            "your Gemini plan's quota ran out for this window. "
            "It comes back on its own — 'nanobridge doctor' shows how much is left and when it resets."
        ),
    },
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
