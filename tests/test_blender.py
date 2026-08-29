"""O refino e o render. Os que rodam o Blender de verdade se pulam sozinhos
quando ele não está na máquina — a CI não tem 400 MB de Blender, e travar a
suíte por isso trocaria uma dependência opcional por obrigatória."""

import numpy as np
import pytest
import trimesh
from PIL import Image

from nanobridge import blender, core
from nanobridge.errors import BlenderMissingError

tem_blender = pytest.mark.skipif(blender.find_blender() is None, reason="Blender não instalado")


def bicho(caminho, subdivisoes=3):
    """Uma esfera colorida: fechada, com normal consistente e cor por vértice —
    o mínimo que o QuadriFlow e a assadura precisam."""
    m = trimesh.creation.icosphere(subdivisions=subdivisoes)
    cores = np.zeros((len(m.vertices), 4), dtype=np.uint8)
    cores[:, 0] = np.clip((m.vertices[:, 0] + 1) * 127, 0, 255)
    cores[:, 1] = np.clip((m.vertices[:, 1] + 1) * 127, 0, 255)
    cores[:, 2] = 200
    cores[:, 3] = 255
    m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=cores)
    m.export(caminho)
    return caminho


def test_acha_o_blender_ou_diz_que_nao_achou():
    achado = blender.find_blender()
    assert achado is None or blender.Path(achado).exists()


def test_variavel_de_ambiente_vem_antes_do_resto(tmp_path, monkeypatch):
    """Quem instalou numa pasta própria não deveria ter que nos convencer."""
    falso = tmp_path / "meu-blender"
    falso.write_text("#!/bin/sh\n")
    monkeypatch.setenv("NANOBRIDGE_BLENDER", str(falso))
    assert blender.find_blender() == str(falso)


def test_sem_blender_o_erro_diz_como_instalar(monkeypatch):
    monkeypatch.setattr(blender, "find_blender", lambda: None)
    with pytest.raises(BlenderMissingError) as erro:
        blender.run("refine.py", {})
    assert "blender" in str(erro.value).lower()


def test_os_scripts_do_blender_estao_no_pacote():
    """Eles são arquivos de dados, não módulos importáveis — se o empacotamento
    deixar de levá-los, o refino some do build instalado e só some lá."""
    for nome in ("refine.py", "render.py"):
        assert (blender.AQUI / nome).exists()


@tem_blender
def test_refino_devolve_quadrilateros_uv_e_textura(tmp_path):
    """O teste central: malha crua → asset. Cada afirmação aqui é uma coisa que
    o gerador 3D NÃO devolve e que sem elas o arquivo não serve fora do Blender."""
    resultado = core.refine_mesh(bicho(tmp_path / "bruta.glb"), out_dir=tmp_path / "saida",
                                 name="bola", faces=800, texture_size=256, formats=[".glb"])
    assert resultado.quad_ratio == 1.0, "a retopologia não pegou: saiu triângulo"
    assert 400 <= resultado.after["faces"] <= 1600
    assert resultado.after["uv_layers"] == 1
    assert resultado.uv_created
    assert resultado.texture and resultado.texture.exists()
    assert resultado.outputs[0].exists()

    pixels = np.asarray(Image.open(resultado.texture).convert("RGB"))
    assert pixels.mean() > 5, "a textura assou preta — a fonte de cor não chegou no bake"


@tem_blender
def test_o_glb_refinado_carrega_a_textura_dentro_dele(tmp_path):
    """Cor por vértice morre em qualquer motor de jogo; textura em UV não. É a
    diferença entre 'a IA cuspiu uma malha' e 'isto é um asset'."""
    resultado = core.refine_mesh(bicho(tmp_path / "b.glb"), out_dir=tmp_path / "s", name="b",
                                 faces=600, texture_size=256, formats=[".glb"])
    cena = trimesh.load(resultado.outputs[0], force="scene")
    malha = next(iter(cena.geometry.values()))
    assert malha.visual.uv is not None
    assert malha.visual.material.baseColorTexture is not None


@tem_blender
def test_sem_retopologia_ele_apenas_reduz(tmp_path):
    resultado = core.refine_mesh(bicho(tmp_path / "b.glb"), out_dir=tmp_path / "s", name="b",
                                 faces=500, retopo=False, texture_size=128, formats=[".glb"])
    assert resultado.after["faces"] <= 520
    assert resultado.quad_ratio < 0.5, "sem retopologia o resultado tem que continuar triangulado"


@tem_blender
def test_exporta_os_formatos_pedidos(tmp_path):
    resultado = core.refine_mesh(bicho(tmp_path / "b.glb"), out_dir=tmp_path / "s", name="b",
                                 faces=400, texture_size=128, formats=[".glb", ".fbx", ".obj", ".blend"])
    assert {p.suffix for p in resultado.outputs} == {".glb", ".fbx", ".obj", ".blend"}
    assert all(p.exists() and p.stat().st_size > 0 for p in resultado.outputs)


@tem_blender
def test_malha_sem_cor_sai_sem_textura_e_avisa(tmp_path):
    """Malha branca (o que o Hunyuan devolve) não tem o que assar. O certo é
    dizer isso, e não gravar um PNG preto fingindo que deu certo."""
    caminho = tmp_path / "branca.glb"
    trimesh.creation.icosphere(subdivisions=3).export(caminho)
    resultado = core.refine_mesh(caminho, out_dir=tmp_path / "s", name="b", faces=400,
                                 texture_size=128, formats=[".glb"])
    assert resultado.texture is None
    assert resultado.after["faces"] > 0


@tem_blender
def test_render_sai_com_fundo_transparente_e_o_objeto_no_meio(tmp_path):
    caminhos = core.render_mesh(bicho(tmp_path / "b.glb"), out_dir=tmp_path / "s", name="b",
                                frames=1, size=128, samples=8)
    pixels = np.asarray(Image.open(caminhos[0]).convert("RGBA"))
    assert pixels.shape[:2] == (128, 128)
    assert pixels[0, 0, 3] == 0, "o canto tinha que ser transparente"
    assert pixels[64, 64, 3] > 200, "o meio tinha que ter objeto"


@tem_blender
def test_o_render_enquadra_igual_em_todos_os_angulos(tmp_path):
    """Mesmo defeito que o rasterizador já tinha: enquadrar quadro a quadro faz
    o objeto crescer ao girar. Aqui a escala é medida na união dos ângulos."""
    caminho = tmp_path / "caixa.glb"
    m = trimesh.creation.box(extents=(2.0, 1.0, 0.4))
    m.export(caminho)
    caminhos = core.render_mesh(caminho, out_dir=tmp_path / "s", name="c", frames=4,
                                size=96, samples=8, pitch=0.0)
    alturas = []
    for arquivo in caminhos:
        alfa = np.asarray(Image.open(arquivo).convert("RGBA"))[:, :, 3] > 8
        linhas = np.nonzero(alfa)[0]
        alturas.append(int(linhas.max() - linhas.min()))
    assert max(alturas) - min(alturas) <= 1, f"a altura variou entre os quadros: {alturas}"


@tem_blender
def test_o_blend_carrega_a_textura_embutida(tmp_path):
    """O .blend guardava só o CAMINHO do PNG, e abrir o arquivo em outra máquina
    mostrava o modelo em magenta — o rosa de "textura faltando" do Blender.
    Medido num baú de tesouro. O teste renderiza o .blend de verdade, porque é
    a única forma de a falha aparecer: o arquivo abre normalmente nos dois casos.
    """
    resultado = core.refine_mesh(bicho(tmp_path / "b.glb"), out_dir=tmp_path / "s", name="b",
                                 faces=500, texture_size=128, formats=[".blend"])
    caminhos = core.render_mesh(resultado.outputs[0], out_dir=tmp_path / "r", name="r",
                                frames=1, size=96, samples=8)
    pixels = np.asarray(Image.open(caminhos[0]).convert("RGBA"))
    visiveis = pixels[pixels[:, :, 3] > 200][:, :3].astype(int)
    assert len(visiveis) > 0
    magenta = (visiveis[:, 0] > 200) & (visiveis[:, 1] < 60) & (visiveis[:, 2] > 200)
    assert magenta.mean() < 0.02, "o .blend renderizou magenta: a textura não foi embutida"


@tem_blender
def test_o_glb_tritura_os_quadrilateros_e_o_blend_nao(tmp_path):
    """Um detalhe que engana: a malha pode ser 100% quadrilátero e o GLB mostrar
    triângulo, porque o formato glTF não tem quadrilátero — ele tritura tudo na
    exportação. Quem quiser ver a topologia abre o .blend, não o .glb."""
    resultado = core.refine_mesh(bicho(tmp_path / "b.glb"), out_dir=tmp_path / "s", name="b",
                                 faces=600, texture_size=128, formats=[".glb"])
    assert resultado.quad_ratio == 1.0
    cena = trimesh.load(resultado.outputs[0], force="scene")
    malha = next(iter(cena.geometry.values()))
    assert malha.faces.shape[1] == 3, "o glTF sempre chega triangulado"
    assert len(malha.faces) >= resultado.after["faces"]


@tem_blender
@pytest.mark.parametrize("alvo", [400, 3000])
def test_a_retopologia_acerta_o_orcamento_em_varias_densidades(tmp_path, alvo):
    """A tentativa é escalonada porque o QuadriFlow recusa a malha inteira por
    causa de **uma** aresta ruim, e a chance de sobrar uma cresce com a densidade
    da entrada decimada. Medido num baú: entrada de 24 mil faces terminou; 40,
    60 e 90 mil cancelaram. Sem escalonar, orçamento alto caía no plano B e
    entregava dez vezes as faces pedidas, dizendo 100% de quadriláteros — o que
    é verdade e não é o que foi pedido.
    """
    resultado = core.refine_mesh(bicho(tmp_path / "b.glb", subdivisoes=4),
                                 out_dir=tmp_path / f"s{alvo}", name="b", faces=alvo,
                                 texture_size=128, formats=[".glb"])
    assert resultado.quad_ratio == 1.0
    assert alvo * 0.5 <= resultado.after["faces"] <= alvo * 1.5, (
        f"pediu {alvo} faces e veio {resultado.after['faces']}"
    )


def test_o_script_de_abertura_compila():
    """Ele viaja como texto em `--python-expr`, então erro de sintaxe só
    apareceria na tela do usuário, com a janela abrindo sem enquadrar nada."""
    import ast

    ast.parse(blender.AO_ABRIR)
    assert "view3d.view_selected" in blender.AO_ABRIR
    assert "bpy.app.timers.register" in blender.AO_ABRIR, (
        "sem temporizador o script roda antes de a janela existir, e `bpy.context.screen` é None"
    )


@tem_blender
def test_o_script_de_abertura_nao_quebra_sem_janela(tmp_path):
    """Rodar sem interface é o pior caso: `bpy.context.screen` não existe. O
    script tem que devolver 'tento de novo' em vez de derrubar o Blender."""
    import subprocess

    saida = subprocess.run(
        [blender.find_blender(), "-b", "--factory-startup", "--python-expr", blender.AO_ABRIR],
        capture_output=True, text=True, timeout=120,
    )
    junto = (saida.stdout + saida.stderr).lower()
    assert "traceback" not in junto and "error:" not in junto


def bicho_texturizado(caminho):
    """Uma malha cuja cor mora numa TEXTURA, não em cor por vértice — que é
    como o TRELLIS entrega, e o caso que o refino ignorava."""
    m = trimesh.creation.icosphere(subdivisions=3)
    verts = np.asarray(m.vertices)
    u = 0.5 + np.arctan2(verts[:, 2], verts[:, 0]) / (2 * np.pi)
    v = 0.5 - np.arcsin(np.clip(verts[:, 1], -1, 1)) / np.pi
    quadros = np.zeros((64, 64, 3), dtype=np.uint8)
    quadros[:32, :, 0] = 220      # metade vermelha, metade azul: fácil de medir
    quadros[32:, :, 2] = 220
    m.visual = trimesh.visual.TextureVisuals(
        uv=np.column_stack([u, v]),
        material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(quadros)),
    )
    m.export(caminho)
    return caminho


@tem_blender
def test_a_cor_que_vem_em_textura_tambem_e_assada(tmp_path):
    """O refino lia cor por vértice e só. Numa malha texturizada ele procurava a
    imagem no material que ele mesmo acabara de criar — vazio, por construção —
    e declarava "esta malha não tem cor". Medido numa gárgula do TRELLIS, que
    chega com UV e textura de 1024 dentro do GLB e saía do refino sem nenhuma.
    """
    resultado = core.refine_mesh(bicho_texturizado(tmp_path / "tex.glb"),
                                 out_dir=tmp_path / "s", name="t", faces=600,
                                 texture_size=256, formats=[".glb"])
    assert resultado.texture is not None, "a textura da origem foi perdida no refino"
    pixels = np.asarray(Image.open(resultado.texture).convert("RGB"))
    visiveis = pixels[pixels.sum(axis=2) > 30]
    assert len(visiveis) > 0
    # As duas cores da origem têm que aparecer na textura assada.
    assert (visiveis[:, 0] > 120).any() and (visiveis[:, 2] > 120).any(), (
        "a assadura saiu monocromática — a textura de origem não chegou ao bake"
    )
