"""Roda DENTRO do Blender. Transforma malha crua de IA em asset utilizável.

Chamado por `nanobridge refine`, nunca importado pelo pacote: o `bpy` só existe
no Python do próprio Blender.

O que o gerador 3D devolve não é asset: é uma casca de centenas de milhares de
triângulos, sem UV, com a cor guardada por vértice — que só o visualizador dele
entende. Abrir isso no Blender dá um borrão cinza. Os passos aqui são os que
qualquer artista faria à mão, na ordem em que se faz:

    limpar → reduzir → suavizar → abrir UV → assar a cor numa textura → exportar

O passo que muda tudo é assar. Cor por vértice morre em qualquer motor de jogo,
em qualquer visualizador de GLB e em qualquer render; uma textura em UV funciona
em todos. É a diferença entre "a IA cuspiu uma malha" e "isto é um asset".

Argumentos vêm depois de `--`, em JSON, para não brigar com os do Blender.
"""

import contextlib
import json
import math
import os
import sys

import bpy


def argumentos() -> dict:
    bruto = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "{}"
    return json.loads(bruto)


def limpar_cena() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def importar(caminho: str) -> None:
    ext = os.path.splitext(caminho)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=caminho)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=caminho)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=caminho)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=caminho)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=caminho)
    else:
        raise SystemExit(f"formato não suportado: {ext}")


def malhas() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def juntar() -> object:
    """Um objeto só. Gerador costuma devolver a malha partida em pedaços, e
    reduzir/desdobrar pedaço a pedaço dá costura visível entre eles."""
    alvos = malhas()
    if not alvos:
        raise SystemExit("o arquivo não tem malha nenhuma")
    bpy.ops.object.select_all(action="DESELECT")
    for objeto in alvos:
        objeto.select_set(True)
    bpy.context.view_layer.objects.active = alvos[0]
    if len(alvos) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def contar(objeto) -> dict:
    malha = objeto.data
    return {
        "vertices": len(malha.vertices),
        "faces": len(malha.polygons),
        "uv_layers": len(malha.uv_layers),
        "color_attributes": len(malha.color_attributes),
        "materials": len(malha.materials),
    }


def costurar(objeto, distancia: float = 0.0001) -> None:
    """Solda vértice duplicado, recalcula normal para fora e joga fora geometria
    solta. Malha de IA vem com tudo isso, e cada um estraga um passo seguinte:
    duplicado abre buraco na UV, normal invertida deixa a face preta, e o cisco
    solto puxa a caixa delimitadora e desenquadra o render."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=distancia)
    # dissolve_degenerate antes de recalcular a normal: face de área zero não
    # tem normal, e é ela que faz o QuadriFlow recusar a malha inteira com
    # "face normals that point in a consistent direction".
    bpy.ops.mesh.dissolve_degenerate()
    bpy.ops.mesh.delete_loose()
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def reduzir(objeto, alvo_faces: int) -> float:
    """Decimate por colapso até o orçamento de faces. Devolve a razão aplicada.

    Um asset de jogo vive na casa dos milhares de triângulos; o gerador entrega
    centenas de milhares. Reduzir antes de desdobrar a UV é obrigatório — a UV é
    calculada sobre a malha final, e desdobrar 300 mil faces para depois jogar
    90% fora produz ilhas quebradas."""
    atual = len(objeto.data.polygons)
    if alvo_faces <= 0 or atual <= alvo_faces:
        return 1.0
    razao = alvo_faces / atual
    mod = objeto.modifiers.new(name="reduzir", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = razao
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return razao


def suavizar(objeto, angulo: float = 40.0) -> None:
    """Sombreado suave com quebra por ângulo: curva fica lisa, quina continua
    quina. Sem isto a malha reduzida fica facetada como bola de discoteca."""
    bpy.ops.object.shade_smooth()
    with contextlib.suppress(Exception):
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angulo))


def desdobrar(objeto, margem: float = 0.02) -> bool:
    """Smart UV Project. Devolve True se precisou criar a UV.

    Sem UV não existe textura, e sem textura a cor não sai do Blender."""
    if objeto.data.uv_layers:
        return False
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(82.0), island_margin=margem)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


def _fonte_de_cor(arvore, malha):
    """O nó que lê a cor de onde ela estiver: atributo de cor por vértice, ou a
    textura que o GLB já trouxe."""
    if malha.color_attributes:
        no = arvore.nodes.new("ShaderNodeVertexColor")
        no.layer_name = malha.color_attributes[0].name
        return no, "Color"
    for no in arvore.nodes:
        if no.type == "TEX_IMAGE" and no.image:
            return no, "Color"
    return None, None


def _material_emissivo(objeto):
    """Prepara o objeto de ORIGEM da assadura: a cor dele vira emissão pura.

    EMIT e não DIFFUSE de propósito. EMIT copia o valor da cor tal e qual, sem
    luz, sem sombra e sem oclusão — que é exatamente o que um mapa de cor base
    tem que ser. DIFFUSE assaria a iluminação da cena junto, e a textura sairia
    com a sombra queimada dentro dela, impossível de desfazer depois.
    """
    malha = objeto.data
    material = bpy.data.materials.new(name="nb_origem")
    material.use_nodes = True
    arvore = material.node_tree
    fonte, saida = _fonte_de_cor(arvore, malha)
    if fonte is None:
        return False
    emissao = arvore.nodes.new("ShaderNodeEmission")
    arvore.links.new(fonte.outputs[saida], emissao.inputs["Color"])
    saida_material = next(n for n in arvore.nodes if n.type == "OUTPUT_MATERIAL")
    arvore.links.new(emissao.outputs["Emission"], saida_material.inputs["Surface"])
    malha.materials.clear()
    malha.materials.append(material)
    return True


def _preparar_cycles(tamanho: int) -> None:
    cena = bpy.context.scene
    try:
        cena.render.engine = "CYCLES"
    except TypeError as erro:  # pragma: no cover - depende da build
        raise SystemExit(f"esta instalação do Blender não tem Cycles: {erro}") from erro
    cena.cycles.device = "CPU"
    cena.cycles.samples = 1  # EMIT não tem ruído: uma amostra basta e é 30x mais rápido
    cena.render.bake.use_pass_direct = False
    cena.render.bake.use_pass_indirect = False
    cena.render.bake.margin = max(4, tamanho // 128)


def assar_cor(destino_obj, tamanho: int, arquivo: str, origem_obj=None,
              extrusao: float = 0.05) -> str | None:
    """Cor → PNG em UV. É o passo que faz o asset existir fora do Blender.

    Com `origem_obj`, assa de uma malha para outra (alta → baixa): é assim que a
    cor da malha densa que a IA devolveu chega na topologia limpa da retopologia,
    e é o mesmo procedimento que um artista usa entre high-poly e low-poly.
    Sem ele, assa o objeto sobre si mesmo.
    """
    fonte = origem_obj or destino_obj
    if not fonte.data.color_attributes and not any(
        n.type == "TEX_IMAGE" and n.image
        for m in fonte.data.materials if m and m.use_nodes
        for n in m.node_tree.nodes
    ):
        return None
    if not _material_emissivo(fonte):
        return None

    material = bpy.data.materials.new(name="nanobridge")
    material.use_nodes = True
    destino_obj.data.materials.clear()
    destino_obj.data.materials.append(material)
    arvore = material.node_tree
    principled = next((n for n in arvore.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        principled = arvore.nodes.new("ShaderNodeBsdfPrincipled")

    imagem = bpy.data.images.new("albedo", width=tamanho, height=tamanho, alpha=False)
    no_textura = arvore.nodes.new("ShaderNodeTexImage")
    no_textura.image = imagem
    arvore.nodes.active = no_textura  # o alvo da assadura é o nó ATIVO

    _preparar_cycles(tamanho)
    bpy.context.scene.render.bake.use_selected_to_active = origem_obj is not None
    if origem_obj is not None:
        bpy.context.scene.render.bake.cage_extrusion = extrusao

    bpy.ops.object.select_all(action="DESELECT")
    if origem_obj is not None:
        origem_obj.select_set(True)
    destino_obj.select_set(True)
    bpy.context.view_layer.objects.active = destino_obj  # o ATIVO recebe
    bpy.ops.object.bake(type="EMIT")

    arvore.links.new(no_textura.outputs["Color"], principled.inputs["Base Color"])
    imagem.filepath_raw = arquivo
    imagem.file_format = "PNG"
    imagem.save()
    return arquivo


def retopologizar(objeto, alvo_faces: int):
    """QuadriFlow: refaz a malha em **quadriláteros**, não em triângulos.

    É o passo que separa "a IA cuspiu uma casca" de "isto é um asset". O gerador
    devolve sopa de triângulo de tamanho irregular — que deforma feio ao animar,
    não aceita loop de aresta e nenhum artista aceitaria. QuadriFlow devolve
    quadrilátero de tamanho parecido, que é o que se modela à mão.

    Devolve o objeto novo; o original fica na cena, porque é dele que a cor vai
    ser assada depois.
    """
    bpy.ops.object.select_all(action="DESELECT")
    objeto.select_set(True)
    bpy.context.view_layer.objects.active = objeto
    bpy.ops.object.duplicate()
    baixa = bpy.context.view_layer.objects.active
    baixa.name = "nanobridge_low"
    # QuadriFlow trabalha melhor com entrada já enxuta, e é ordens de grandeza
    # mais rápido: reduzir para umas poucas dezenas de milhares primeiro é o que
    # faz o passo custar segundos em vez de minutos.
    reduzir(baixa, min(60000, max(alvo_faces * 4, 20000)))
    # Limpar DE NOVO, agora depois de reduzir. O decimate colapsa aresta e cria
    # face degenerada nova, e o QuadriFlow recusa por causa dela — medido num
    # baú de tesouro: com a limpeza só antes de reduzir ele cancelava; com esta
    # segunda passada, terminou em 5 519 quadriláteros.
    costurar(baixa)

    def tentar():
        try:
            return bpy.ops.object.quadriflow_remesh(
                target_faces=int(alvo_faces), use_preserve_sharp=False,
                use_preserve_boundary=True, smooth_normals=True)
        except RuntimeError:
            return {"CANCELLED"}

    if "FINISHED" not in tentar():
        # QuadriFlow exige malha fechada e sem borda solta, e reconstrução de IA
        # frequentemente não é: sobra buraco, face invertida, aresta com três
        # faces. Medido num baú de tesouro — o operador desistia **em silêncio**
        # e o resultado saía com 0% de quadriláteros, sem nenhum aviso.
        #
        # O remesh por voxel resolve porque ele não conserta a malha: ele
        # redesenha a superfície inteira a partir do volume, e o que sai é
        # fechado por construção. Perde detalhe fino, e é por isso que é plano B.
        voxel = baixa.modifiers.new(name="voxel", type="REMESH")
        voxel.mode = "VOXEL"
        voxel.voxel_size = max(baixa.dimensions) / 128.0
        bpy.ops.object.modifier_apply(modifier=voxel.name)
        if "FINISHED" not in tentar():
            return baixa, "decimate"
        return baixa, "quadriflow-voxel"
    return baixa, "quadriflow"


def exportar(objeto, caminho: str) -> None:
    ext = os.path.splitext(caminho)[1].lower()
    bpy.ops.object.select_all(action="DESELECT")
    objeto.select_set(True)
    bpy.context.view_layer.objects.active = objeto
    if ext in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(filepath=caminho, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
                                  use_selection=True)
    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(filepath=caminho, use_selection=True, path_mode="COPY", embed_textures=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_export(filepath=caminho, export_selected_objects=True, export_materials=True)
    elif ext == ".usdz":
        bpy.ops.wm.usd_export(filepath=caminho, selected_objects_only=True)
    elif ext == ".blend":
        # Embutir a textura antes de salvar. Sem isto o .blend guarda só o
        # CAMINHO do PNG, e abrir o arquivo em outra máquina (ou depois de mover
        # a pasta) mostra o modelo em magenta — o rosa de "textura faltando" do
        # Blender. Medido exatamente assim num baú.
        with contextlib.suppress(RuntimeError):
            bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=caminho)
    else:
        raise SystemExit(f"formato de saída não suportado: {ext}")


def main() -> None:
    cfg = argumentos()
    limpar_cena()
    importar(cfg["input"])
    objeto = juntar()
    antes = contar(objeto)

    alvo = int(cfg.get("faces", 0))
    vai_retopologizar = bool(cfg.get("retopo")) and alvo > 0

    # Soldar a malha densa ANTES da retopologia é o que quebra o QuadriFlow, e
    # foi medido: `remove_doubles` na malha de 279 mil faces de um baú criava
    # **uma** aresta não-manifold, e uma só basta para o QuadriFlow recusar a
    # malha inteira ("needs to be manifold"). Sem soldar antes: 5 519
    # quadriláteros. Com: cancelado, e o resultado saía triangulado sem aviso.
    #
    # Na retopologia a solda não faz falta nenhuma: a malha densa serve só de
    # fonte de cor para a assadura, e cor não liga para topologia.
    if cfg.get("weld", True) and not vai_retopologizar:
        costurar(objeto, cfg.get("weld_distance", 0.0001))

    alta = None   # a malha densa que sobra da retopologia
    razao = 1.0
    metodo = "decimate"
    if vai_retopologizar:
        alta = objeto
        objeto, metodo = retopologizar(alta, alvo)
    else:
        razao = reduzir(objeto, alvo)
    origem = alta  # de quem a cor é assada: a densa que a retopologia deixou

    if cfg.get("smooth", True):
        suavizar(objeto, cfg.get("smooth_angle", 40.0))
    uv_nova = desdobrar(objeto, cfg.get("uv_margin", 0.02)) if cfg.get("unwrap", True) else False

    textura = None
    if cfg.get("bake", True):
        textura = assar_cor(objeto, int(cfg.get("texture_size", 1024)), cfg["texture_out"],
                            origem_obj=origem, extrusao=cfg.get("cage_extrusion", 0.05))

    if alta is not None:
        bpy.data.objects.remove(alta, do_unlink=True)

    malha = objeto.data
    quads = sum(1 for p in malha.polygons if len(p.vertices) == 4)
    depois = contar(objeto)
    depois["quads"] = quads
    depois["quad_ratio"] = round(quads / max(len(malha.polygons), 1), 3)

    for saida in cfg["outputs"]:
        exportar(objeto, saida)

    print("NANOBRIDGE_JSON " + json.dumps({
        "before": antes,
        "after": depois,
        "decimate_ratio": round(razao, 4),
        "retopo": vai_retopologizar,
        "retopo_method": metodo,
        "color_source": "self" if origem is not None else None,
        "uv_created": uv_nova,
        "texture": textura,
        "outputs": cfg["outputs"],
    }))


main()
