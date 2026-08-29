"""Falar com o Blender de fora: achar o executável e rodar os scripts daqui.

O Blender não é biblioteca Python — o `bpy` só existe dentro dele. Então o
contrato é processo: a gente monta um JSON, chama `blender -b --python arquivo --
<json>`, e lê de volta a linha que começa com `NANOBRIDGE_JSON`.

Ler só essa linha não é preguiça: o Blender escreve dezenas de linhas de log,
aviso de versão de arquivo e progresso de render no stdout, e nenhuma delas é
resposta. Um marcador é mais barato e mais robusto que tentar calar o programa.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .. import errors

AQUI = Path(__file__).resolve().parent
MARCADOR = "NANOBRIDGE_JSON "

#: Onde o Blender costuma estar, por sistema. A variável de ambiente vem antes
#: de tudo: quem instalou numa pasta própria não deveria ter que nos convencer.
CAMINHOS = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/Applications/Blender/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    r"C:\Program Files\Blender Foundation\Blender\blender.exe",
)


#: O que roda quando a janela abre. Sem isto o Blender mostra a cena com a vista
#: padrão e o modelo aparece do tamanho de um grão no meio da grade — a malha
#: reconstruída mede cerca de um metro, e a vista padrão enquadra dez. E o
#: sombreado padrão é cinza chapado, que esconde justamente a textura que o
#: refino acabou de assar.
AO_ABRIR = """
import bpy


def _nanobridge_enquadrar():
    tela = getattr(bpy.context, "screen", None)
    if tela is None:
        return 0.2      # a janela ainda nao existe: tenta de novo daqui a pouco
    for area in tela.areas:
        if area.type != "VIEW_3D":
            continue
        area.spaces[0].shading.type = "MATERIAL"
        regiao = next((r for r in area.regions if r.type == "WINDOW"), None)
        if regiao is None:
            continue
        try:
            with bpy.context.temp_override(area=area, region=regiao):
                bpy.ops.object.select_all(action="SELECT")
                bpy.ops.view3d.view_selected()
        except Exception:
            pass
    return None


bpy.app.timers.register(_nanobridge_enquadrar, first_interval=0.2)
""".strip()


def find_blender() -> str | None:
    de_fora = os.environ.get("NANOBRIDGE_BLENDER")
    if de_fora and Path(de_fora).exists():
        return de_fora
    no_path = shutil.which("blender")
    if no_path:
        return no_path
    for candidato in CAMINHOS:
        if Path(candidato).exists():
            return candidato
    return None


def version() -> str | None:
    binario = find_blender()
    if not binario:
        return None
    try:
        saida = subprocess.run([binario, "--version"], capture_output=True, text=True, timeout=60)
        return saida.stdout.strip().splitlines()[0] if saida.stdout else None
    except Exception:
        return None


def run(script: str, config: dict, *, timeout: int = 900) -> dict:
    """Roda um script daqui dentro do Blender e devolve o JSON que ele imprimiu."""
    binario = find_blender()
    if not binario:
        raise errors.BlenderMissingError()

    processo = subprocess.run(
        [binario, "-b", "--factory-startup", "--python", str(AQUI / script), "--", json.dumps(config)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    for linha in processo.stdout.splitlines():
        if linha.startswith(MARCADOR):
            return json.loads(linha[len(MARCADOR):])

    # Sem a linha, o script morreu. A última linha de erro do Blender é a que
    # diz por quê; despejar o log inteiro esconderia ela no meio de ruído.
    pistas = [
        linha for linha in (processo.stdout + processo.stderr).splitlines()
        if any(marca in linha for marca in ("Error", "error:", "Traceback", "SystemExit", "Exception"))
    ]
    raise errors.BlenderError(pistas[-1] if pistas else f"exit {processo.returncode}")
