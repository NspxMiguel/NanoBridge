"""CLI do NanoBridge. Tudo que o servidor MCP faz, dá para fazer aqui na mão."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, atlas_formats, config, core, imaging, palettes
from .backends import all_backends, pick
from .backends.web import find_cookies as web_find_cookies
from .errors import NanoBridgeError
from .i18n import SUPPORTED, t


def _common(parser: argparse.ArgumentParser, *, post: bool = True) -> None:
    parser.add_argument("-o", "--out", type=Path, help="pasta de saída / output folder")
    parser.add_argument("-n", "--name", help="nome base do arquivo / file stem")
    parser.add_argument("-b", "--backend", choices=("web", "api"), help="canal / backend")
    parser.add_argument("-m", "--model", help="modelo / model")
    parser.add_argument("--open", action="store_true", help="abrir ao terminar / open when done")
    parser.add_argument("--json", action="store_true", help="saída JSON / JSON output")
    if post:
        parser.add_argument("--transparent", action="store_true", help="fundo transparente")
        parser.add_argument("--no-transparent", dest="transparent", action="store_false")
        parser.add_argument("--trim", action="store_true", help="cortar moldura vazia")
        parser.add_argument("--no-trim", dest="trim", action="store_false")
        parser.add_argument("--size", type=int, help="lado máximo em px / max side in px")
        parser.add_argument("--tolerance", type=int, default=24, help="tolerância de cor do fundo")
        parser.add_argument(
            "--palette",
            help="travar nas cores de uma paleta: nome embutido, arquivo .hex, "
            "ou lista #RRGGBB,#RRGGBB / lock to a palette",
        )
        parser.add_argument("--dither", action="store_true", help="difusão de erro ao quantizar")
        parser.add_argument(
            "--pixels",
            type=int,
            help="pixels de arte no lado maior: a grade fecha certo / art pixels on the long side",
        )
        parser.add_argument("--zoom", type=int, default=1, help="ampliar por inteiro / integer upscale")
        parser.add_argument("--retries", type=int, default=2, help="tentativas extras se vier texto")
        parser.set_defaults(transparent=None, trim=None)


def _post_kwargs(args: argparse.Namespace) -> dict:
    out: dict = {}
    for key in ("transparent", "trim"):
        value = getattr(args, key, None)
        if value is not None:
            out[key] = value
    if getattr(args, "size", None):
        out["size"] = args.size
    if getattr(args, "tolerance", None) is not None:
        out["tolerance"] = args.tolerance
    if getattr(args, "palette", None):
        out["palette"] = args.palette
    if getattr(args, "dither", False):
        out["dither"] = True
    if getattr(args, "pixels", None):
        out["pixels"] = args.pixels
    if getattr(args, "zoom", 1) and args.zoom > 1:
        out["zoom"] = args.zoom
    if getattr(args, "retries", None) is not None:
        out["retries"] = args.retries
    return out


def _run_kwargs(args: argparse.Namespace) -> dict:
    kwargs = _post_kwargs(args)
    kwargs.update(
        out_dir=args.out,
        backend_name=args.backend,
        model=args.model,
    )
    if getattr(args, "name", None):
        kwargs["name"] = args.name
    if getattr(args, "conversation", None):
        kwargs["conversation"] = args.conversation
    return {k: v for k, v in kwargs.items() if v is not None}


def _open_files(paths: list[Path]) -> None:
    """Abre no visualizador do sistema. Nunca derruba o comando por isso.

    O pacote declara Python 3.11+ e não macOS: fora do Mac o `open` nem existe,
    e a imagem já está salva — falhar aqui trocaria o resultado por um erro.
    """
    opener = {"darwin": ["open"], "win32": ["cmd", "/c", "start", ""]}.get(sys.platform, ["xdg-open"])
    for path in paths:
        try:
            subprocess.run([*opener, str(path)], check=False)
        except OSError:
            print(f"nanobridge: {t('gen.saved', path=path)}", file=sys.stderr)
            return


def _report(result: core.Generated, args: argparse.Namespace) -> None:
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "paths": [str(p) for p in result.paths],
                    "frames": [str(p) for p in result.frames],
                    "gif": str(result.gif) if result.gif else None,
                    "backend": result.backend,
                    "model": result.model,
                    "conversation": result.conversation,
                    "text": result.text,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    for path in result.paths:
        print(t("gen.saved", path=path))
    if result.frames:
        cols, rows = result.grid or ("?", "?")
        print(t("sheet.sliced", n=len(result.frames), cols=cols, rows=rows, path=result.frames[0].parent))
    if result.gif:
        print(t("sheet.gif", path=result.gif))
    if getattr(args, "open", False):
        targets = [result.gif] if result.gif else result.paths
        _open_files(targets)


async def _cmd_setup(args: argparse.Namespace) -> int:
    """Primeiro uso guiado. Existe porque a pergunta óbvia — 'como eu faço
    login?' — tem uma resposta que ninguém adivinha: você não faz.

    O `doctor` diz o estado para quem já sabe o que procurar. Isto conduz quem
    está chegando: explica que não há login, encontra a sessão, abre o Gemini
    quando falta, e prova o caminho inteiro gerando uma imagem de verdade em vez
    de dizer "deve funcionar".
    """
    from .backends.web import WebBackend

    print(t("setup.title"))
    print()
    print("  " + t("setup.no_login"))
    print()

    step = 1

    def say(state: str, text: str) -> None:
        print(f"  {state} {t('setup.step', n=step, what=text)}")

    # 1 — a sessão existe no navegador?
    cookies = web_find_cookies()
    if not cookies:
        say("--", t("setup.checking_cookies") + ": " + t("setup.not_found"))
        if not args.no_open:
            print("     " + t("setup.opening"))
            _open_urls(["https://gemini.google.com"])
        print()
        print("  " + t("setup.not_ready"))
        return 1
    say("OK", t("setup.checking_cookies") + ": " + t("setup.found", browser=cookies.get("_source", "?")))
    step += 1

    # 2 — a sessão está viva? (o cookie pode existir e estar morto)
    backend = WebBackend()
    try:
        quota = await backend.quota()
    except NanoBridgeError as exc:
        say("--", t("setup.checking_session") + f": {exc}")
        print()
        print("  " + t("setup.not_ready"))
        return 1
    say("OK", t("setup.checking_session") + ": " + t("setup.session_ok", tier=quota.get("tier", "?")))
    step += 1

    # 3 — o caminho inteiro funciona? Só uma geração real prova.
    if not args.no_test:
        say("..", t("setup.generating"))
        try:
            result = await core.sprite(
                "a small green slime, friendly face",
                size=96,
                out_dir=args.out or config.default_out_dir(),
                name="nanobridge-setup-test",
                backend=backend,
            )
        except NanoBridgeError as exc:
            say("--", f"{exc}")
            print()
            print("  " + t("setup.not_ready"))
            return 1
        say("OK", t("setup.generated", path=result.paths[0]))
        step += 1

    # 4 — o Claude Code enxerga o servidor?
    binary = shutil.which("nanobridge") or sys.argv[0]
    registered = _mcp_is_registered()
    if registered:
        say("OK", t("setup.mcp_ok"))
    else:
        say("--", t("setup.mcp_missing", bin=binary))

    print()
    print("  " + t("setup.ready"))
    return 0


def _mcp_is_registered() -> bool:
    """O Claude Code conhece o servidor? Ausência de `claude` não é falha."""
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        out = subprocess.run([claude, "mcp", "list"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return "nanobridge" in out.stdout


def _open_urls(urls: list[str]) -> None:
    opener = {"darwin": ["open"], "win32": ["cmd", "/c", "start", ""]}.get(sys.platform, ["xdg-open"])
    for url in urls:
        try:
            subprocess.run([*opener, url], check=False)
        except OSError:
            print(f"     {url}", file=sys.stderr)


async def _cmd_doctor(args: argparse.Namespace) -> int:
    print(t("doctor.title"))
    ready = False
    for backend in all_backends():
        ok = backend.available()
        ready = ready or ok
        mark = "OK " if ok else "-- "
        state = t("doctor.ready") if ok else t("doctor.unavailable")
        print(f"  {mark}{backend.name:4} {state:12} {backend.status()}")
    if not ready:
        print(t("doctor.hint_none"))
        return 1
    try:
        backend = pick(args.backend)
        quota = await backend.quota() if hasattr(backend, "quota") else {}
        for label, value in quota.items():
            print(f"  {t('doctor.quota')}: {label} {value}")
        await backend.close()
    except NanoBridgeError as exc:
        print(f"  ! {exc}")
        return 1
    print(f"  {t('doctor.pillow_ok')}")
    print(f"  {t('cfg.path', path=config.config_path())}")
    return 0


async def _cmd_gen(args: argparse.Namespace) -> int:
    result = await core.generate(args.prompt, files=args.file or None, **_run_kwargs(args))
    _report(result, args)
    return 0


async def _cmd_sprite(args: argparse.Namespace) -> int:
    result = await core.sprite(args.subject, style=args.style, **_run_kwargs(args))
    _report(result, args)
    return 0


async def _cmd_icon(args: argparse.Namespace) -> int:
    result = await core.icon(args.subject, style=args.style, **_run_kwargs(args))
    _report(result, args)
    return 0


async def _cmd_edit(args: argparse.Namespace) -> int:
    result = await core.edit(args.image, args.prompt, **_run_kwargs(args))
    _report(result, args)
    return 0


def _seam_line(seam: dict) -> str:
    return t(
        "tex.seam",
        h=f"{seam.get('horizontal', 0):.2f}",
        v=f"{seam.get('vertical', 0):.2f}",
        limit=core.SEAM_THRESHOLD,
    )


async def _cmd_variations(args: argparse.Namespace) -> int:
    """Várias opções do mesmo assunto, para escolher olhando."""
    result = await core.variations(
        args.subject,
        args.count,
        style=args.style,
        size=args.size,
        out_dir=args.out,
        name=args.name,
        contact_sheet=not args.no_sheet,
        backend_name=args.backend,
        palette=args.palette,
        pixels=args.pixels,
        zoom=args.zoom,
        retries=args.retries,
    )
    if args.json:
        print(json.dumps({
            "paths": [str(p) for p in result.paths],
            "contact_sheet": str(result.contact_sheet) if result.contact_sheet else None,
            "failed": result.failed,
        }, ensure_ascii=False, indent=2))
    else:
        for path in result.paths:
            print(t("gen.saved", path=path))
        if result.contact_sheet:
            print(t("gen.saved", path=result.contact_sheet))
        for why in result.failed:
            print(why, file=sys.stderr)
    if args.open and result.contact_sheet:
        _open_files([result.contact_sheet])
    return 1 if not result.paths else 0


async def _cmd_texture(args: argparse.Namespace) -> int:
    """Textura que repete, com a emenda medida — não só prometida."""
    result = await core.texture(
        args.subject,
        style=args.style,
        repair=not args.no_repair,
        threshold=args.threshold,
        preview=args.preview,
        blend=args.blend,
        **_run_kwargs(args),
    )
    if args.json:
        print(json.dumps({
            "path": str(result.path),
            "seam": result.seam,
            "seam_before": result.seam_before,
            "repaired": result.repaired,
            "preview": str(result.preview) if result.preview else None,
        }, ensure_ascii=False, indent=2))
        return 0
    print(t("gen.saved", path=result.path))
    if result.repaired:
        print(t("tex.repaired",
                before=f"{max(result.seam_before.values()):.2f}",
                after=f"{max(result.seam.values()):.2f}"))
    else:
        print(t("tex.clean"))
    print(_seam_line(result.seam))
    if result.preview:
        print(t("gen.saved", path=result.preview))
    return 0


def _cmd_normal(args: argparse.Namespace) -> int:
    """Mapa de normais para luz dinâmica em 2D. Local, sem cota."""
    out = core.build_normal_map(args.image, out=args.out, strength=args.strength, blur=args.blur)
    print(t("gen.saved", path=out))
    return 0


def _gen_only_kwargs(args: argparse.Namespace) -> dict:
    """Só o que a geração da referência entende.

    `_run_kwargs` não serve aqui: ele carrega `size`, `pixels` e `palette`, que
    no 3D pertencem ao **render** da malha e não à imagem de referência — e a
    referência quer justamente o oposto (grande, colorida, sem paleta travada).
    """
    kwargs = {"out_dir": args.out, "backend_name": args.backend, "model": args.model,
              "name": getattr(args, "name", None)}
    return {k: v for k, v in kwargs.items() if v is not None}


def _mesh_stage(args):
    """Diz em que passo está. Vai para stderr: em pipe, a saída limpa importa."""
    import sys

    def contar(marca):
        if marca == "reference":
            print(t("mesh3d.stage_reference"), file=sys.stderr)
        else:
            print(t("mesh3d.stage_engine", engine=marca.label), file=sys.stderr)

    return None if getattr(args, "quiet", False) else contar


def _cmd_mesh(args: argparse.Namespace) -> int:
    """Imagem → malha 3D."""
    resultado = core.mesh_from_image(
        args.image, out_dir=args.out, name=args.name, engine=args.engine,
        on_stage=_mesh_stage(args),
    )
    print(t("gen.saved", path=resultado.path))
    print(t("mesh3d.made_by", engine=resultado.engine_label, license=resultado.license))
    print(t("mesh3d.stats", **resultado.stats))
    if resultado.stats["depth_ratio"] < 0.10:
        print(t("mesh3d.flat_warning"))
    if args.open:
        _open_files([resultado.path])
    return 0


def _cmd_turntable(args: argparse.Namespace) -> int:
    """Malha → as N direções, já como sprite 2D."""
    resultado = core.render_turntable(
        args.mesh, out_dir=args.out, name=args.name, frames=args.frames, size=args.size,
        pitch=args.pitch, start=args.start, zoom=args.zoom, engine=args.engine,
        sheet=not args.no_sheet, gif=args.gif, fps=args.fps, pixels=args.pixels,
        palette=args.palette,
    )
    for caminho in resultado.frames:
        print(t("gen.saved", path=caminho))
    for extra in (resultado.sheet, resultado.gif):
        if extra:
            print(t("gen.saved", path=extra))
    if args.open:
        _open_files([resultado.sheet or resultado.frames[0]])
    return 0


async def _cmd_sprite3d(args: argparse.Namespace) -> int:
    """Prompt → referência → malha → folha de direções, de uma vez."""
    resultado = await core.sprite_3d(
        args.subject, engine=args.engine,
        frames=args.frames, size=args.size, pitch=args.pitch, zoom=args.zoom,
        gif=args.gif, fps=args.fps, pixels=args.pixels, palette=args.palette,
        reference=args.reference, on_stage=_mesh_stage(args), **_gen_only_kwargs(args),
    )
    if resultado.source_image:
        print(t("gen.saved", path=resultado.source_image))
    print(t("gen.saved", path=resultado.path))
    print(t("mesh3d.made_by", engine=resultado.engine_label, license=resultado.license))
    print(t("mesh3d.stats", **resultado.stats))
    for caminho in resultado.frames:
        print(t("gen.saved", path=caminho))
    for extra in (resultado.sheet, resultado.gif):
        if extra:
            print(t("gen.saved", path=extra))
    if args.open:
        _open_files([p for p in (resultado.sheet, resultado.path) if p])
    return 0


def _cmd_tile(args: argparse.Namespace) -> int:
    """Medir, consertar e pré-visualizar a emenda de uma imagem local."""
    if args.repair:
        out = core.repair_tileable(args.image, out=args.out, blend=args.blend)
        print(t("gen.saved", path=out))
        print(_seam_line(core.check_tileable(out)))
        return 0
    seam = core.check_tileable(args.image)
    if args.json:
        print(json.dumps(seam, indent=2))
    else:
        print(_seam_line(seam))
    if args.preview:
        print(t("gen.saved", path=core.tile_preview(args.image, times=args.times)))
    return 0


async def _cmd_animate(args: argparse.Namespace) -> int:
    """Anima um sprite que já existe, mantendo o personagem."""
    result = await core.animate(
        args.image,
        args.action,
        grid=args.grid,
        fps=args.fps,
        frame_size=args.frame_size,
        gif=not args.no_gif,
        **_run_kwargs(args),
    )
    _report(result, args)
    return 0


async def _cmd_sheet(args: argparse.Namespace) -> int:
    result = await core.sheet(
        args.subject,
        grid=args.grid,
        action=args.action,
        style=args.style,
        fps=args.fps,
        frame_size=args.frame_size,
        gif=not args.no_gif,
        **_run_kwargs(args),
    )
    _report(result, args)
    return 0


def _cmd_slice(args: argparse.Namespace) -> int:
    source = core.existing_path(args.image)
    cols, rows = imaging.parse_grid(args.grid)
    img = imaging.open_image(source)
    if args.transparent:
        img = imaging.make_transparent(img, tol=args.tolerance)
    out = Path(args.out or Path(args.image).with_suffix("")).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem
    paths = []
    for index, frame in enumerate(imaging.slice_sheet(img, cols, rows), start=1):
        if args.size:
            frame = imaging.fit(frame, args.size)
        path = out / f"{stem}-{index:02d}.png"
        frame.save(path)
        paths.append(path)
    print(t("sheet.sliced", n=len(paths), cols=cols, rows=rows, path=out))
    if not args.no_gif:
        gif = imaging.save_gif([imaging.open_image(p) for p in paths], out / f"{stem}.gif", fps=args.fps)
        print(t("sheet.gif", path=gif))
    return 0


def _cmd_cut(args: argparse.Namespace) -> int:
    """Pós-processamento puro: nenhuma rede, serve para imagem de qualquer origem."""
    img = imaging.open_image(core.existing_path(args.image))
    if args.transparent:
        img = imaging.make_transparent(img, tol=args.tolerance)
    if args.trim:
        img = imaging.trim(img, tol=args.tolerance)
    if args.size:
        img = imaging.fit(img, args.size, pad=False)
    if args.pixels:
        img = imaging.pixelate(img, args.pixels, zoom=args.zoom)
    elif args.zoom > 1:
        img = img.resize((img.width * args.zoom, img.height * args.zoom), imaging.Image.NEAREST)
    if args.palette:
        img = imaging.quantize_to_palette(img, core.palettes.resolve(args.palette), dither=args.dither)
    out = Path(args.out) if args.out else Path(args.image).with_name(f"{Path(args.image).stem}-cut.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(t("gen.saved", path=out))
    return 0


def _cmd_atlas(args: argparse.Namespace) -> int:
    """Empacota sprites soltos num atlas + manifesto — nada de rede, nada de cota."""
    images = [Path(p) for p in args.image]
    if args.dir:
        images += sorted(Path(args.dir).glob("*.png"))
    result = core.build_atlas(
        images,
        out_dir=args.out,
        name=args.name,
        padding=args.padding,
        max_width=args.max_width,
        formats=args.format,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "path": str(result.path),
                    "manifest": str(result.manifest_path),
                    "manifests": {k: str(v) for k, v in result.manifests.items()},
                    "sprites": [
                        {"name": e.name, "x": e.x, "y": e.y, "w": e.w, "h": e.h} for e in result.entries
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(t("atlas.packed", n=len(result.entries), path=result.path, manifest=result.manifest_path))
    return 0


async def _cmd_cast(args: argparse.Namespace) -> int:
    """Um elenco inteiro coerente, num comando."""
    result = await core.cast(
        args.subject,
        style=args.style,
        palette=args.palette or "auto",
        size=args.size,
        out_dir=args.out,
        atlas=not args.no_atlas,
        formats=args.format,
        atlas_name=args.name,
        pixels=args.pixels,
        zoom=args.zoom,
        dither=args.dither,
        tolerance=args.tolerance,
        trim=args.trim,
        transparent=args.transparent,
        backend_name=args.backend,
        model=args.model,
        retries=args.retries,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "sprites": [str(s.paths[0]) for s in result.sprites],
                    "palette": [core.palettes.rgb_to_hex(c) for c in result.palette],
                    "atlas": str(result.atlas.path) if result.atlas else None,
                    "manifests": (
                        {k: str(v) for k, v in result.atlas.manifests.items()} if result.atlas else {}
                    ),
                    "failed": result.failed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for generated in result.sprites:
            print(t("gen.saved", path=generated.paths[0]))
        if result.palette:
            shown = " ".join(core.palettes.rgb_to_hex(c) for c in result.palette[:8])
            print(t("cast.palette", colours=shown))
        if result.atlas:
            print(t("atlas.packed", n=len(result.atlas.entries), path=result.atlas.path,
                    manifest=", ".join(str(v) for v in result.atlas.manifests.values())))
        for subject, why in result.failed.items():
            print(t("cast.failed", subject=subject, why=why), file=sys.stderr)
    if args.open and (result.atlas or result.sprites):
        _open_files([result.atlas.path] if result.atlas else [s.paths[0] for s in result.sprites])
    return 1 if not result.sprites else 0


def _cmd_palettes(args: argparse.Namespace) -> int:
    """Lista as paletas embutidas, com as cores, para escolher sem adivinhar."""
    print(t("palette.list"))
    for name in palettes.names():
        colours = palettes.resolve(name)
        print(f"  {name:16} {len(colours):>3} " + " ".join(palettes.rgb_to_hex(c) for c in colours[:8]))
    return 0


def _cmd_palette(args: argparse.Namespace) -> int:
    """Extrai a paleta de uma imagem, ou reescreve uma imagem numa paleta."""
    if args.apply:
        out = core.apply_palette(args.image, args.apply, out=args.out, dither=args.dither)
        print(t("palette.applied", path=out))
        return 0

    colours = core.palette_from_image(args.image, count=args.count)
    if args.json:
        print(json.dumps([palettes.rgb_to_hex(c) for c in colours], indent=2))
        return 0
    print(t("palette.extracted", n=len(colours), src=args.image))
    for colour in colours:
        print(f"  {palettes.rgb_to_hex(colour)}")
    if args.out:
        print(t("palette.saved", path=palettes.save(colours, Path(args.out))))
    return 0


def _cmd_lang(args: argparse.Namespace) -> int:
    if args.lang not in SUPPORTED:
        print(t("cfg.lang_bad", lang=args.lang), file=sys.stderr)
        return 2
    path = config.set_language(args.lang)
    print(t("cfg.lang_set", lang=args.lang))
    print(t("cfg.path", path=path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanobridge",
        description="Nano Banana (Gemini) image generation for agents — CLI + MCP.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"nanobridge {__version__}")
    parser.add_argument("--lang", choices=SUPPORTED, help="idioma desta execução / language for this run")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="primeiro uso guiado / guided first run")
    setup.add_argument("--no-test", action="store_true", help="não gerar a imagem de prova")
    setup.add_argument("--no-open", action="store_true", help="não abrir o navegador")
    setup.add_argument("-o", "--out", type=Path)
    setup.set_defaults(func=_cmd_setup, is_async=True)

    doctor = sub.add_parser("doctor", help="o que está pronto / what is ready")
    doctor.add_argument("-b", "--backend", choices=("web", "api"))
    doctor.set_defaults(func=_cmd_doctor, is_async=True)

    gen = sub.add_parser("gen", help="imagem livre / free-form image")
    gen.add_argument("prompt")
    gen.add_argument("-f", "--file", action="append", help="imagem de referência / reference image")
    gen.add_argument("--conversation", help="continuar uma conversa / continue a conversation")
    _common(gen)
    gen.set_defaults(func=_cmd_gen, is_async=True)

    sprite = sub.add_parser("sprite", help="sprite de jogo / game sprite")
    sprite.add_argument("subject")
    sprite.add_argument("-s", "--style", default="pixel", help="pixel, flat, cartoon, 3d, realistic, sketch")
    _common(sprite)
    sprite.set_defaults(func=_cmd_sprite, is_async=True)

    icon = sub.add_parser("icon", help="ícone / app icon")
    icon.add_argument("subject")
    icon.add_argument("-s", "--style", default="flat")
    _common(icon)
    icon.set_defaults(func=_cmd_icon, is_async=True)

    edit = sub.add_parser("edit", help="editar uma imagem / edit an image")
    edit.add_argument("image")
    edit.add_argument("prompt")
    edit.add_argument("--conversation")
    _common(edit)
    edit.set_defaults(func=_cmd_edit, is_async=True)

    sheet = sub.add_parser("sheet", help="folha de sprites + GIF / sprite sheet + GIF")
    sheet.add_argument("subject")
    sheet.add_argument("-g", "--grid", default="4x2")
    sheet.add_argument("-a", "--action", default="a simple looping idle animation")
    sheet.add_argument("-s", "--style", default="pixel")
    sheet.add_argument("--fps", type=int, default=10)
    sheet.add_argument("--frame-size", type=int)
    sheet.add_argument("--no-gif", action="store_true")
    _common(sheet)
    sheet.set_defaults(func=_cmd_sheet, is_async=True)

    variations = sub.add_parser(
        "variations", help="N opções do mesmo assunto / N options of the same subject"
    )
    variations.add_argument("subject")
    variations.add_argument("-c", "--count", type=int, default=4)
    variations.add_argument("-s", "--style", default="pixel")
    variations.add_argument("--size", type=int, default=160)
    variations.add_argument("--palette")
    variations.add_argument("--pixels", type=int)
    variations.add_argument("--zoom", type=int, default=1)
    variations.add_argument("--no-sheet", action="store_true")
    variations.add_argument("-o", "--out", type=Path)
    variations.add_argument("-n", "--name")
    variations.add_argument("-b", "--backend", choices=("web", "api"))
    variations.add_argument("--retries", type=int, default=2)
    variations.add_argument("--open", action="store_true")
    variations.add_argument("--json", action="store_true")
    variations.set_defaults(func=_cmd_variations, is_async=True)

    texture = sub.add_parser(
        "texture", help="textura que repete, emenda medida / verified tileable texture"
    )
    texture.add_argument("subject")
    texture.add_argument("-s", "--style", default="realistic")
    texture.add_argument("--no-repair", action="store_true")
    texture.add_argument("--threshold", type=float, default=core.SEAM_THRESHOLD)
    texture.add_argument("--blend", type=float, default=0.12)
    texture.add_argument("--preview", action="store_true", help="gravar uma grade 3x3")
    _common(texture)
    texture.set_defaults(func=_cmd_texture, is_async=True)

    normal = sub.add_parser("normal", help="mapa de normais para luz 2D / normal map for 2D lighting")
    normal.add_argument("image")
    normal.add_argument("-o", "--out")
    normal.add_argument("--strength", type=float, default=2.0)
    normal.add_argument("--blur", type=float, default=1.0)
    normal.set_defaults(func=_cmd_normal, is_async=False)

    def _turntable_flags(parser_):
        parser_.add_argument("--frames", type=int, default=8,
                             help="quantas direções / how many directions")
        parser_.add_argument("--size", type=int, default=192)
        parser_.add_argument("--pitch", type=float, default=core.DEFAULT_PITCH,
                             help="inclinação da câmera; 30 = isométrica / camera tilt; 30 = isometric")
        parser_.add_argument("--zoom", type=float, default=0.92)
        parser_.add_argument("--gif", action="store_true")
        parser_.add_argument("--fps", type=int, default=12)
        parser_.add_argument("--pixels", type=int,
                             help="reduzir a uma grade de N pixels / crush to an N-pixel grid")
        parser_.add_argument("--palette",
                             help="nome de paleta ou lista de cores / palette name or colour list")

    mesh = sub.add_parser("mesh", help="imagem → malha 3D / image → 3D mesh")
    mesh.add_argument("image")
    mesh.add_argument("--engine", help="triposr | hunyuan")
    mesh.add_argument("-o", "--out", type=Path, help="pasta de saída / output folder")
    mesh.add_argument("-n", "--name")
    mesh.add_argument("--open", action="store_true")
    mesh.add_argument("--quiet", action="store_true")
    mesh.set_defaults(func=_cmd_mesh, is_async=False)

    turntable = sub.add_parser(
        "turntable", help="malha → sprite das N direções / mesh → an N-direction sprite"
    )
    turntable.add_argument("mesh")
    turntable.add_argument("--engine", help="de qual motor veio, para alinhar a frente")
    turntable.add_argument("--start", type=float, help="ângulo do primeiro quadro / yaw of frame 1")
    turntable.add_argument("--no-sheet", action="store_true")
    turntable.add_argument("-o", "--out", type=Path, help="pasta de saída / output folder")
    turntable.add_argument("-n", "--name")
    turntable.add_argument("--open", action="store_true")
    _turntable_flags(turntable)
    turntable.set_defaults(func=_cmd_turntable, is_async=False)

    sprite3d = sub.add_parser(
        "sprite3d", help="prompt → malha → sprite das N direções / prompt → mesh → N-direction sprite"
    )
    sprite3d.add_argument("subject")
    sprite3d.add_argument("--engine", help="triposr | hunyuan")
    sprite3d.add_argument("--reference",
                          help="pular a geração e usar esta imagem / skip generation, use this image")
    sprite3d.add_argument("--quiet", action="store_true")
    _turntable_flags(sprite3d)
    _common(sprite3d, post=False)
    sprite3d.set_defaults(func=_cmd_sprite3d, is_async=True)

    tile = sub.add_parser(
        "tile", help="medir/consertar a emenda / measure or repair a seam"
    )
    tile.add_argument("image")
    tile.add_argument("--repair", action="store_true")
    tile.add_argument("--preview", action="store_true")
    tile.add_argument("--times", type=int, default=3)
    tile.add_argument("--blend", type=float, default=0.12)
    tile.add_argument("-o", "--out")
    tile.add_argument("--json", action="store_true")
    tile.set_defaults(func=_cmd_tile, is_async=False)

    animate = sub.add_parser("animate", help="animar um sprite existente / animate an existing sprite")
    animate.add_argument("image")
    animate.add_argument("action", nargs="?", default="a simple looping idle animation")
    animate.add_argument("-g", "--grid", default="4x1")
    animate.add_argument("--fps", type=int, default=10)
    animate.add_argument("--frame-size", type=int)
    animate.add_argument("--no-gif", action="store_true")
    _common(animate)
    animate.set_defaults(func=_cmd_animate, is_async=True)

    slice_ = sub.add_parser("slice", help="cortar folha local / slice a local sheet")
    slice_.add_argument("image")
    slice_.add_argument("-g", "--grid", default="4x2")
    slice_.add_argument("-o", "--out", type=Path)
    slice_.add_argument("--size", type=int)
    slice_.add_argument("--fps", type=int, default=10)
    slice_.add_argument("--transparent", action="store_true")
    slice_.add_argument("--tolerance", type=int, default=24)
    slice_.add_argument("--no-gif", action="store_true")
    slice_.set_defaults(func=_cmd_slice, is_async=False)

    cut = sub.add_parser("cut", help="recortar / limpar fundo local")
    cut.add_argument("image")
    cut.add_argument("-o", "--out")
    cut.add_argument("--transparent", action="store_true", default=True)
    cut.add_argument("--no-transparent", dest="transparent", action="store_false")
    cut.add_argument("--trim", action="store_true", default=True)
    cut.add_argument("--no-trim", dest="trim", action="store_false")
    cut.add_argument("--size", type=int)
    cut.add_argument("--pixels", type=int, help="pixels de arte no lado maior")
    cut.add_argument("--zoom", type=int, default=1)
    cut.add_argument("--palette")
    cut.add_argument("--dither", action="store_true")
    cut.add_argument("--tolerance", type=int, default=24)
    cut.set_defaults(func=_cmd_cut, is_async=False)

    cast = sub.add_parser("cast", help="um elenco coerente de uma vez / a whole coherent cast at once")
    cast.add_argument("subject", nargs="+")
    cast.add_argument("-s", "--style", default="pixel")
    cast.add_argument("--size", type=int, default=128)
    cast.add_argument(
        "--palette",
        help="paleta do elenco; o padrão 'auto' tira do primeiro sprite / "
        "cast palette; default 'auto' takes it from the first sprite",
    )
    cast.add_argument("--pixels", type=int, help="pixels de arte no lado maior / art pixels")
    cast.add_argument("--zoom", type=int, default=1)
    cast.add_argument("--dither", action="store_true")
    cast.add_argument("--tolerance", type=int, default=24)
    # `--no-trim` mantém todos os sprites do mesmo tamanho, que é o que se quer
    # quando o atlas vai virar quadros de tamanho fixo num motor.
    cast.add_argument("--trim", action="store_true", default=True)
    cast.add_argument("--no-trim", dest="trim", action="store_false")
    cast.add_argument("--transparent", action="store_true", default=True)
    cast.add_argument("--no-transparent", dest="transparent", action="store_false")
    cast.add_argument("--open", action="store_true", help="abrir o atlas ao terminar")
    cast.add_argument("--no-atlas", action="store_true")
    cast.add_argument("-f", "--format", action="append", choices=atlas_formats.FORMATS)
    cast.add_argument("-o", "--out", type=Path)
    cast.add_argument("-n", "--name", help="nome do atlas / atlas name")
    cast.add_argument("-b", "--backend", choices=("web", "api"))
    cast.add_argument("-m", "--model")
    cast.add_argument("--retries", type=int, default=2)
    cast.add_argument("--json", action="store_true")
    cast.set_defaults(func=_cmd_cast, is_async=True)

    atlas = sub.add_parser("atlas", help="empacotar sprites soltos / pack loose sprites into an atlas")
    atlas.add_argument("image", nargs="*", help="arquivos PNG / PNG files")
    atlas.add_argument("--dir", help="pasta inteira de PNGs / a whole folder of PNGs")
    atlas.add_argument("-o", "--out", type=Path)
    atlas.add_argument("-n", "--name")
    atlas.add_argument("--padding", type=int, default=2)
    atlas.add_argument("--max-width", type=int, default=2048)
    atlas.add_argument(
        "-f",
        "--format",
        action="append",
        choices=atlas_formats.FORMATS,
        help="formato do manifesto, repetível / manifest format, repeatable",
    )
    atlas.add_argument("--json", action="store_true")
    atlas.set_defaults(func=_cmd_atlas, is_async=False)

    sub.add_parser("palettes", help="paletas embutidas / built-in palettes").set_defaults(
        func=_cmd_palettes, is_async=False
    )

    palette = sub.add_parser("palette", help="extrair ou aplicar paleta / extract or apply a palette")
    palette.add_argument("image")
    palette.add_argument("--apply", help="paleta a aplicar / palette to apply")
    palette.add_argument("-n", "--count", type=int, default=16)
    palette.add_argument("-o", "--out")
    palette.add_argument("--dither", action="store_true")
    palette.add_argument("--json", action="store_true")
    palette.set_defaults(func=_cmd_palette, is_async=False)

    lang = sub.add_parser("lang", help="idioma salvo / saved language")
    lang.add_argument("lang", choices=SUPPORTED)
    lang.set_defaults(func=_cmd_lang, is_async=False)

    mcp = sub.add_parser("mcp", help="servidor MCP (stdio) / MCP server (stdio)")
    mcp.set_defaults(func=None, is_async=False)

    return parser


def main(argv: list[str] | None = None) -> int:
    config.apply_saved_language()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.lang:
        from . import i18n

        i18n.set_language(args.lang)

    if args.command == "mcp":
        from .mcp_server import run

        run()
        return 0

    try:
        if args.is_async:
            return asyncio.run(_with_cleanup(args))
        return args.func(args)
    except NanoBridgeError as exc:
        print(f"nanobridge: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"nanobridge: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Caminho que não existe, que já existe como arquivo, que é pasta, sem
        # permissão: tudo isso é o mundo dizendo não, não é defeito do programa.
        print(f"nanobridge: {exc}", file=sys.stderr)
        return 2


async def _with_cleanup(args: argparse.Namespace) -> int:
    from .backends.web import WebBackend

    try:
        return await args.func(args)
    finally:
        # A sessão web mantém uma tarefa de refresh viva; sem fechar, o processo
        # do CLI não termina.
        await WebBackend().close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
