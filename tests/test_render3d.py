"""O rasterizador. Tudo aqui é local e determinístico — nenhum teste toca a rede."""

import numpy as np
import pytest
import trimesh
from PIL import Image

from nanobridge import render3d
from nanobridge.errors import EmptyMeshError


def caixa(cor=(200, 60, 60, 255), tamanho=(1.0, 2.0, 0.5)):
    """Um paralelepípedo colorido: dimensões diferentes em cada eixo, para o
    teste de enquadramento notar quando o objeto vira de lado."""
    m = trimesh.creation.box(extents=tamanho)
    m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=np.tile(cor, (len(m.vertices), 1)))
    return m


def salva(tmp_path, malha, nome="m.glb"):
    caminho = tmp_path / nome
    malha.export(caminho)
    return caminho


def test_load_mesh_centraliza_e_normaliza(tmp_path):
    m = caixa(tamanho=(3.0, 1.0, 1.0))
    m.apply_translation([50.0, -20.0, 7.0])
    carregada = render3d.load_mesh(salva(tmp_path, m))
    centro = carregada.bounds.mean(axis=0)
    assert np.allclose(centro, 0.0, atol=1e-6), "sem centrar, o objeto nasce fora do quadro"
    assert (carregada.bounds[1] - carregada.bounds[0]).max() == pytest.approx(1.0, abs=1e-6)


def test_load_mesh_recusa_arquivo_sem_face(tmp_path):
    caminho = tmp_path / "vazio.ply"
    trimesh.PointCloud(np.zeros((3, 3))).export(caminho)
    with pytest.raises(EmptyMeshError):
        render3d.load_mesh(caminho)


def test_normais_apontam_para_fora_da_esfera():
    """Prova contra a verdade analítica, não contra outra biblioteca.

    Numa esfera centrada na origem a normal exata de cada vértice é a própria
    posição normalizada. É o teste certo para a conta própria (bincount, sem
    SciPy), que existe por velocidade: sem ele, um erro de sinal ou de índice
    viraria "o sombreado ficou estranho" e ninguém saberia onde olhar.
    """
    m = trimesh.creation.icosphere(subdivisions=3)
    exato = np.asarray(m.vertices) / np.linalg.norm(m.vertices, axis=1, keepdims=True)
    nosso = render3d.vertex_normals(m)
    assert np.abs((nosso * exato).sum(axis=1) - 1.0).max() < 1e-3


def test_normais_concordam_com_o_trimesh_dentro_da_diferenca_de_peso():
    """Concordam em direção, e não são idênticas de propósito: o trimesh pondera
    a face pelo ângulo do canto, e aqui a ponderação é por área — que sai de
    graça do produto vetorial não normalizado. Em malha real a diferença fica
    abaixo de meio grau; travar em igualdade exata seria travar na escolha
    deles."""
    m = trimesh.creation.icosphere(subdivisions=2)
    cosseno = (render3d.vertex_normals(m) * np.asarray(m.vertex_normals)).sum(axis=1)
    assert np.degrees(np.arccos(np.clip(cosseno, -1, 1))).max() < 1.0


def test_turntable_devolve_n_quadros_do_tamanho_pedido(tmp_path):
    m = render3d.load_mesh(salva(tmp_path, caixa()))
    quadros = render3d.turntable(m, frames=6, size=48)
    assert len(quadros) == 6
    assert all(q.size == (48, 48) and q.mode == "RGBA" for q in quadros)


def test_fundo_fica_transparente(tmp_path):
    m = render3d.load_mesh(salva(tmp_path, caixa(tamanho=(0.4, 0.4, 0.4))))
    quadro = render3d.turntable(m, frames=1, size=64)[0]
    alfa = np.asarray(quadro)[:, :, 3]
    assert alfa[0, 0] == 0 and alfa[-1, -1] == 0
    assert alfa.max() == 255, "o objeto tem que aparecer opaco no meio"


def test_o_objeto_nao_muda_de_tamanho_ao_girar(tmp_path):
    """O defeito que o enquadramento comum conserta.

    Uma caixa larga e rasa é grande de frente e estreita de lado. Enquadrando
    quadro a quadro ela pulsa; num sprite de jogo isso é inaceitável, porque o
    personagem cresceria ao virar.
    """
    m = render3d.load_mesh(salva(tmp_path, caixa(tamanho=(2.0, 1.0, 0.3))))
    alturas = []
    for quadro in render3d.turntable(m, frames=8, size=64):
        ys = np.nonzero(np.asarray(quadro)[:, :, 3] > 8)[0]
        alturas.append(int(ys.max() - ys.min()))
    assert len(set(alturas)) == 1, f"a altura variou entre os quadros: {alturas}"


def test_mesma_malha_dois_renders_mesmos_pixels(tmp_path):
    """A amostragem é aleatória, e a semente é fixa justamente para isto."""
    caminho = salva(tmp_path, caixa())
    a = render3d.turntable(render3d.load_mesh(caminho), frames=2, size=40)
    b = render3d.turntable(render3d.load_mesh(caminho), frames=2, size=40)
    for x, y in zip(a, b, strict=True):
        assert np.array_equal(np.asarray(x), np.asarray(y))


def test_a_face_da_frente_tapa_a_de_tras(tmp_path):
    """Prova do buffer de profundidade: duas placas, cores diferentes, uma atrás
    da outra. Sem ordenação por profundidade a de trás vazaria por cima."""
    frente = trimesh.creation.box(extents=(1.0, 1.0, 0.05))
    frente.apply_translation([0, 0, 0.5])
    frente.visual = trimesh.visual.ColorVisuals(
        frente, vertex_colors=np.tile((255, 0, 0, 255), (len(frente.vertices), 1))
    )
    tras = trimesh.creation.box(extents=(1.0, 1.0, 0.05))
    tras.apply_translation([0, 0, -0.5])
    tras.visual = trimesh.visual.ColorVisuals(
        tras, vertex_colors=np.tile((0, 0, 255, 255), (len(tras.vertices), 1))
    )
    cena = trimesh.util.concatenate([frente, tras])
    m = render3d.load_mesh(salva(tmp_path, cena))
    pixels = np.asarray(render3d.render_view(m, yaw=0, size=64))
    meio = pixels[32, 32]
    assert meio[3] == 255
    assert meio[0] > meio[2], f"a placa de trás vazou por cima: {meio.tolist()}"


def test_pitch_muda_o_desenho(tmp_path):
    m = render3d.load_mesh(salva(tmp_path, caixa(tamanho=(1.0, 1.0, 1.0))))
    reto = np.asarray(render3d.render_view(m, yaw=0, pitch=0, size=48))
    inclinado = np.asarray(render3d.render_view(m, yaw=0, pitch=35, size=48))
    assert not np.array_equal(reto, inclinado)


def test_supersample_desligado_ainda_desenha(tmp_path):
    m = render3d.load_mesh(salva(tmp_path, caixa()))
    quadro = render3d.render_view(m, size=32, supersample=1)
    assert quadro.size == (32, 32)
    assert np.asarray(quadro)[:, :, 3].max() == 255


def test_malha_sem_cor_nao_sai_preta(tmp_path):
    """Malha branca (o que o Hunyuan devolve) tem que virar barro claro, não
    silhueta — senão o sprite some no fundo."""
    m = trimesh.creation.icosphere(subdivisions=2)
    carregada = render3d.load_mesh(salva(tmp_path, m))
    pixels = np.asarray(render3d.render_view(carregada, size=48))
    visivel = pixels[pixels[:, :, 3] > 200]
    assert len(visivel) > 0
    assert visivel[:, :3].mean() > 60, "o objeto saiu escuro demais para ler a forma"


def test_render_view_aceita_arrays_prontos(tmp_path):
    """Reusar a nuvem de pontos é o que faz a volta custar um adensamento só."""
    m = render3d.load_mesh(salva(tmp_path, caixa()))
    arrays = render3d.densify(m, 32 * 32)
    quadro = render3d.render_view(arrays, yaw=90, size=32)
    assert isinstance(quadro, Image.Image)
