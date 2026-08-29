"""Os motores 3D. Nenhum teste chama a rede: o cliente do Gradio é substituído."""

import numpy as np
import pytest
import trimesh

from nanobridge import core, mesh3d
from nanobridge.errors import MeshBackendError


def malha_falsa(caminho):
    m = trimesh.creation.box(extents=(1.0, 2.0, 0.8))
    m.export(caminho)
    return str(caminho)


def test_collect_acha_a_malha_na_tupla_do_triposr(tmp_path):
    obj = malha_falsa(tmp_path / "a.obj")
    glb = malha_falsa(tmp_path / "a.glb")
    achados = mesh3d._collect((obj, glb))
    # GLB primeiro: ele carrega a cor por vértice dentro do arquivo, e o .obj
    # depende de um .mtl que o download não traz junto.
    assert achados[0] == glb


def test_collect_acha_a_malha_no_dicionario_do_hunyuan(tmp_path):
    glb = malha_falsa(tmp_path / "b.glb")
    resposta = [{"value": glb, "__type__": "update"}, "<iframe src='...'></iframe>", {"model": {}}]
    assert mesh3d._collect(resposta) == [glb]


def test_collect_ignora_caminho_que_nao_existe():
    assert mesh3d._collect(["/nao/existe/x.glb", "só texto"]) == []


def test_motor_desconhecido_diz_quais_existem():
    with pytest.raises(MeshBackendError) as erro:
        mesh3d.find("inventado")
    assert "triposr" in str(erro.value)


def test_a_fila_passa_para_o_proximo_motor_quando_o_primeiro_cai(tmp_path, monkeypatch):
    """O motivo de existir mais de um motor: Space público cai e volta sozinho,
    e travar no primeiro transformaria indisponibilidade de fora em defeito
    nosso."""
    glb = malha_falsa(tmp_path / "bom.glb")
    chamados = []

    class ClienteFalso:
        def __init__(self, espaco):
            self.espaco = espaco

    def cliente(espaco):
        chamados.append(espaco)
        return ClienteFalso(espaco)

    monkeypatch.setattr(mesh3d, "_client", cliente)
    monkeypatch.setattr(
        mesh3d.TripoSR, "call", lambda self, c, img: (_ for _ in ()).throw(RuntimeError("fila cheia"))
    )
    monkeypatch.setattr(mesh3d.Hunyuan, "call", lambda self, c, img: [{"value": glb}])

    saida, motor = mesh3d.to_mesh(glb, tmp_path / "saida.glb")
    assert motor.name == "hunyuan"
    assert saida.exists()
    assert len(chamados) == 2


def test_quando_todos_caem_o_erro_lista_cada_recusa(tmp_path, monkeypatch):
    glb = malha_falsa(tmp_path / "c.glb")
    monkeypatch.setattr(mesh3d, "_client", lambda espaco: object())
    for classe in (mesh3d.TripoSR, mesh3d.Hunyuan):
        monkeypatch.setattr(
            classe, "call", lambda self, c, img: (_ for _ in ()).throw(RuntimeError("caiu"))
        )
    with pytest.raises(MeshBackendError) as erro:
        mesh3d.to_mesh(glb, tmp_path / "x.glb")
    assert "triposr" in str(erro.value) and "hunyuan" in str(erro.value)


def test_cada_motor_declara_para_onde_o_modelo_nasce_olhando():
    """`front_yaw` é o que põe o rosto no quadro 1. Sem ele a folha de direções
    começa pelas costas — foi assim na primeira medição do TripoSR."""
    for motor in mesh3d.ENGINES:
        assert 0.0 <= motor.front_yaw < 360.0
        assert motor.license, f"{motor.name} sem licença declarada"


def test_stats_separam_volume_de_placa(tmp_path):
    """A razão de profundidade é o número que denuncia arte 2D chapada entrando
    como referência: o modelo devolve um relevo, não um objeto."""
    volume = tmp_path / "volume.glb"
    trimesh.creation.icosphere(subdivisions=2).export(volume)
    assert core.mesh_stats(volume)["depth_ratio"] > 0.9

    placa = tmp_path / "placa.glb"
    trimesh.creation.box(extents=(1.0, 1.0, 0.03)).export(placa)
    assert core.mesh_stats(placa)["depth_ratio"] < 0.10


def test_turntable_escreve_quadros_folha_e_gif(tmp_path):
    caminho = tmp_path / "m.glb"
    trimesh.creation.icosphere(subdivisions=2).export(caminho)
    r = core.render_turntable(caminho, out_dir=tmp_path / "saida", name="bicho",
                              frames=4, size=32, gif=True)
    assert len(r.frames) == 4 and all(p.exists() for p in r.frames)
    assert r.sheet.exists() and r.gif.exists()
    from PIL import Image
    assert Image.open(r.sheet).size == (32 * 4, 32)


def test_turntable_alinha_a_frente_pelo_motor(tmp_path):
    """Quadro 1 tem que ser a frente. Passar `engine` é o que escolhe o ângulo
    inicial certo, e dois motores com convenções opostas têm que render
    diferente."""
    caminho = tmp_path / "m.glb"
    trimesh.creation.box(extents=(1.0, 2.0, 0.4)).export(caminho)
    a = core.render_turntable(caminho, out_dir=tmp_path / "a", name="a", frames=1, size=32,
                              engine="triposr", sheet=False)
    b = core.render_turntable(caminho, out_dir=tmp_path / "b", name="b", frames=1, size=32,
                              engine="hunyuan", sheet=False)
    from PIL import Image
    assert not np.array_equal(np.asarray(Image.open(a.frames[0])), np.asarray(Image.open(b.frames[0])))


def test_turntable_com_paleta_trava_as_cores(tmp_path):
    caminho = tmp_path / "m.glb"
    trimesh.creation.icosphere(subdivisions=2).export(caminho)
    r = core.render_turntable(caminho, out_dir=tmp_path / "p", name="p", frames=2, size=32,
                              palette="gameboy", sheet=False)
    from PIL import Image
    pixels = np.asarray(Image.open(r.frames[0]).convert("RGBA"))
    visiveis = {tuple(c) for c in pixels[pixels[:, :, 3] > 200][:, :3]}
    assert len(visiveis) <= 4, f"a paleta do Game Boy tem 4 cores, saíram {len(visiveis)}"
