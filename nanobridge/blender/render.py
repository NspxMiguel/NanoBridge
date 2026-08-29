"""Roda DENTRO do Blender. Render de verdade da malha, com luz e material.

O rasterizador NumPy do `turntable` existe para ser rápido, determinístico e não
depender de nada — e ele resolve o sprite pequeno. Isto aqui resolve outra coisa:
mostrar o modelo **como ele é**, com sombra projetada, oclusão, reflexo e
antialiasing de motor de render. É a imagem que se põe num README, e é a prova
de que a malha aguenta ser vista de perto.

Argumentos vêm depois de `--`, em JSON.
"""

import contextlib
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector


def argumentos() -> dict:
    return json.loads(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "{}")


def importar(caminho: str) -> None:
    ext = os.path.splitext(caminho)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=caminho)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=caminho)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=caminho)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=caminho)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=caminho)
    else:
        raise SystemExit(f"formato não suportado: {ext}")


def _pontos(objetos, teto: int = 20000):
    """Vértices em espaço de mundo. A caixa delimitadora não serve: ela mede o
    envelope alinhado aos eixos, e um objeto largo e baixo (um cogumelo, por
    exemplo) tem canto de caixa muito mais longe que qualquer ponto real — o
    enquadramento sairia com metade do quadro vazia."""
    pontos = []
    for obj in objetos:
        matriz = obj.matrix_world
        vertices = obj.data.vertices
        passo = max(1, len(vertices) // max(teto // max(len(objetos), 1), 1))
        # `vertices[::passo]` levanta "slice steps not supported": coleção do
        # Blender não é lista de Python. Indexar na mão é o caminho.
        pontos.extend(matriz @ vertices[i].co for i in range(0, len(vertices), passo))
    return pontos


def enquadrar(objetos, angulos, inclinacao: float, zoom: float = 0.9):
    """Câmera ortográfica, com um enquadramento que serve a TODOS os ângulos.

    Ortográfica pelo mesmo motivo do rasterizador: girando em perspectiva, a
    parte que chega mais perto da lente incha, e num quadro de sprite isso lê
    como o personagem mudando de tamanho. A escala é medida na união das
    silhuetas de cada ângulo da volta, e não ângulo a ângulo, pela mesma razão.
    """
    pontos = _pontos(objetos)
    centro = sum(pontos, Vector((0, 0, 0))) / len(pontos)
    minimo = Vector(min(p[i] for p in pontos) for i in range(3))
    maximo = Vector(max(p[i] for p in pontos) for i in range(3))
    centro = (minimo + maximo) / 2
    raio = max((p - centro).length for p in pontos)

    maior = 0.0
    for angulo in angulos:
        rot = Matrix.Rotation(-angulo, 4, "Z") @ Matrix.Rotation(-inclinacao, 4, "X")
        vistos = [rot @ (p - centro) for p in pontos]
        largura = max(v.x for v in vistos) - min(v.x for v in vistos)
        altura = max(v.z for v in vistos) - min(v.z for v in vistos)
        maior = max(maior, largura, altura)

    camera_data = bpy.data.cameras.new("nb_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = maior / max(zoom, 0.05)
    camera = bpy.data.objects.new("nb_cam", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    pivo = bpy.data.objects.new("nb_pivo", None)
    bpy.context.scene.collection.objects.link(pivo)
    pivo.location = centro
    camera.parent = pivo
    camera.location = (0, -raio * 6, 0)
    camera.rotation_euler = (math.radians(90), 0, 0)
    return pivo, centro, raio


def iluminar(centro, raio: float, forca: float = 1.0) -> None:
    """Três pontos: principal, preenchimento e contra-luz.

    É o esquema de estúdio, e existe por um motivo mensurável: com uma luz só, a
    face oposta cai para preto e a silhueta some contra o fundo. A contra-luz é
    a que separa o objeto do fundo, e é a que mais falta quando um render parece
    amador.
    """
    mundo = bpy.data.worlds.new("nb_mundo")
    mundo.use_nodes = True
    mundo.node_tree.nodes["Background"].inputs[0].default_value = (0.16, 0.17, 0.19, 1)
    mundo.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    bpy.context.scene.world = mundo

    for nome, direcao, energia, cor in (
        ("principal", (-1.0, -1.0, 1.2), 2.4, (1.0, 0.97, 0.92)),
        ("preenchimento", (1.4, -0.8, 0.3), 0.9, (0.85, 0.9, 1.0)),
        ("contra", (0.2, 1.6, 0.9), 1.6, (1.0, 1.0, 1.0)),
    ):
        dados = bpy.data.lights.new(f"nb_{nome}", type="AREA")
        dados.energy = energia * forca * (raio * 10) ** 2
        dados.size = raio * 2.5
        dados.color = cor
        luz = bpy.data.objects.new(f"nb_{nome}", dados)
        bpy.context.scene.collection.objects.link(luz)
        vetor = Vector(direcao).normalized() * raio * 4
        luz.location = centro + vetor
        luz.rotation_euler = (-vetor).to_track_quat("-Z", "Y").to_euler()


def configurar(motor: str, tamanho: int, amostras: int, transparente: bool) -> None:
    cena = bpy.context.scene
    # O identificador do EEVEE mudou entre versões do Blender ("BLENDER_EEVEE"
    # até a 4.1, "BLENDER_EEVEE_NEXT" na 4.2/4.3, e de volta a "BLENDER_EEVEE"
    # na 5). Perguntar ao enum é a única forma que não quebra na próxima.
    disponiveis = [i.identifier for i in
                   bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    if motor == "cycles":
        alvo = "CYCLES"
    else:
        alvo = next((n for n in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE") if n in disponiveis),
                    disponiveis[0])
    cena.render.engine = alvo
    cena.render.resolution_x = cena.render.resolution_y = tamanho
    cena.render.resolution_percentage = 100
    cena.render.film_transparent = transparente
    cena.render.image_settings.file_format = "PNG"
    cena.render.image_settings.color_mode = "RGBA" if transparente else "RGB"
    # AgX é o padrão do Blender desde a 4.0 e é feito para cinema: ele dessatura
    # de propósito para segurar realce estourado. Num retrato de asset isso é o
    # oposto do que se quer — a cor tem que sair igual à do mapa que foi assado.
    # Medido: o cogumelo marrom e creme saía cinza-sépia em AgX.
    try:
        cena.view_settings.view_transform = "Standard"
        cena.view_settings.look = "None"
    except TypeError:  # pragma: no cover - build sem OCIO padrão
        pass
    if motor == "cycles":
        cena.cycles.device = "CPU"
        cena.cycles.samples = amostras
        cena.cycles.use_denoising = True
    else:
        with contextlib.suppress(AttributeError):
            cena.eevee.taa_render_samples = amostras


def main() -> None:
    cfg = argumentos()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    importar(cfg["input"])
    objetos = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objetos:
        raise SystemExit("o arquivo não tem malha nenhuma")

    quadros = int(cfg.get("frames", 1))
    inclinacao = math.radians(float(cfg.get("pitch", 15.0)))
    inicio = math.radians(float(cfg.get("start", 0.0)))
    angulos = [inicio + math.radians(360.0 / max(quadros, 1)) * i for i in range(quadros)]

    pivo, centro, raio = enquadrar(objetos, angulos, inclinacao, float(cfg.get("zoom", 0.9)))
    iluminar(centro, raio, float(cfg.get("light", 1.0)))
    configurar(cfg.get("engine", "eevee"), int(cfg.get("size", 512)),
               int(cfg.get("samples", 64)), bool(cfg.get("transparent", True)))
    saidas = []
    for indice, angulo in enumerate(angulos):
        pivo.rotation_euler = (inclinacao, 0.0, angulo)
        destino = cfg["out_pattern"] % (indice + 1)
        bpy.context.scene.render.filepath = destino
        bpy.ops.render.render(write_still=True)
        saidas.append(destino)

    print("NANOBRIDGE_JSON " + json.dumps({
        "frames": saidas,
        "engine": bpy.context.scene.render.engine,
        "radius": round(raio, 4),
    }))


main()
