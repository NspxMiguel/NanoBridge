"""O segundo motor: a IA que devolve geometria, não imagem.

O Nano Banana faz pixel. Nenhum prompt vai fazer ele cuspir malha — e quem
disser o contrário sobre um modelo de imagem está vendendo alguma coisa. Então
o 3D entra por outro modelo, de outra família: **reconstrução de imagem única**
(single-image-to-3D), que olha uma foto e devolve um objeto fechado.

Os dois se encaixam bem porque um resolve o problema do outro: esses modelos
precisam de uma imagem limpa, centrada, de fundo liso — que é exatamente o que
o Nano Banana sabe desenhar sob encomenda.

Continua tudo gratuito. Os motores rodam em Space público da Hugging Face, sem
chave e sem conta; o preço é a fila, e por isso existe mais de um na lista.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import Mesh3DUnavailableError, MeshBackendError, NoMeshEngineError

#: Quanto esperar um Space acordar antes de passar para o próximo da fila.
CONNECT_TIMEOUT = 40.0


@dataclass(frozen=True)
class Engine:
    """Um motor 3D. `front_yaw` é o que alinha a frente do modelo com o quadro 0.

    Cada modelo escolhe para que lado o objeto nasce olhando, e essa escolha não
    está documentada em lugar nenhum — foi medida renderizando a volta inteira e
    olhando qual ângulo mostra o rosto.
    """

    name: str
    label: str
    space: str
    endpoint: str
    front_yaw: float = 180.0
    colored: bool = True
    license: str = ""
    #: Roda em ZeroGPU. Anônimo recebe zero segundo de cota, então sem token
    #: este motor nunca responde — e é melhor pular do que gastar a viagem.
    needs_token: bool = False

    def call(self, client, image: str):  # pragma: no cover - cada motor difere
        raise NotImplementedError


@dataclass(frozen=True)
class TripoSR(Engine):
    def call(self, client, image: str):
        from gradio_client import handle_file

        # O /preprocess recorta o fundo e centraliza. Pular ele e mandar a
        # imagem crua faz o modelo tentar reconstruir o fundo junto, e o
        # resultado é o personagem colado numa placa.
        preparada = client.predict(handle_file(image), True, 0.85, api_name="/preprocess")
        return client.predict(handle_file(preparada), 320, api_name="/generate")


@dataclass(frozen=True)
class Hunyuan(Engine):
    def call(self, client, image: str):
        from gradio_client import handle_file

        return client.predict(
            caption=None,
            image=handle_file(image),
            steps=30,
            guidance_scale=5.0,
            seed=1234,
            octree_resolution=256,
            check_box_rembg=True,
            num_chunks=8000,
            randomize_seed=False,
            api_name=self.endpoint,
        )


@dataclass(frozen=True)
class Trellis(Engine):
    def call(self, client, image: str):
        from gradio_client import handle_file

        # A sessão é obrigatória: sem ela o Space responde com o estado de outra
        # pessoa, ou com nenhum.
        with contextlib.suppress(Exception):
            client.predict(api_name="/start_session")
        return client.predict(
            image=handle_file(image), multiimages=[], seed=0,
            ss_guidance_strength=7.5, ss_sampling_steps=12,
            slat_guidance_strength=3.0, slat_sampling_steps=12,
            multiimage_algo="stochastic", mesh_simplify=0.95, texture_size=1024,
            api_name=self.endpoint,
        )


@dataclass(frozen=True)
class Hi3DGen(Engine):
    def call(self, client, image: str):
        from gradio_client import handle_file

        preparada = client.predict(image=handle_file(image), api_name="/preprocess_image")
        alvo = preparada if isinstance(preparada, str) else image
        return client.predict(
            image=handle_file(alvo), seed=0, ss_guidance_strength=3, ss_sampling_steps=50,
            slat_guidance_strength=3.0, slat_sampling_steps=6, api_name=self.endpoint,
        )


#: Ordem de preferência. O TripoSR vem primeiro porque devolve **cor por
#: vértice** — um sprite precisa da cor, e a malha branca do Hunyuan exige
#: pintar depois. O Hunyuan fica como segunda opção porque a geometria dele é
#: melhor, e às vezes é isso que se quer.
ENGINES: tuple[Engine, ...] = (
    Hunyuan(
        name="hunyuan21",
        label="Hunyuan3D-2.1 (Tencent)",
        space="tencent/Hunyuan3D-2.1",
        endpoint="/shape_generation",
        front_yaw=0.0,
        colored=False,
        license="Tencent Hunyuan Community",
        needs_token=False,
    ),
    TripoSR(
        name="triposr",
        label="TripoSR (Stability AI + Tripo)",
        space="stabilityai/TripoSR",
        endpoint="/generate",
        front_yaw=180.0,
        colored=True,
        license="MIT",
    ),
    Hunyuan(
        name="hunyuan",
        label="Hunyuan3D-2 (Tencent)",
        space="tencent/Hunyuan3D-2",
        endpoint="/shape_generation",
        front_yaw=0.0,
        colored=False,
        license="Tencent Hunyuan Community",
    ),
    Trellis(
        name="trellis",
        label="TRELLIS (Microsoft)",
        space="trellis-community/TRELLIS",
        endpoint="/generate_and_extract_glb",
        front_yaw=180.0,
        colored=True,
        license="MIT",
        needs_token=True,
    ),
    Hi3DGen(
        name="hi3dgen",
        label="Hi3DGen (Stable-X)",
        space="Stable-X/Hi3DGen",
        endpoint="/generate_3d",
        front_yaw=180.0,
        colored=False,
        license="MIT",
        needs_token=True,
    ),
)


def find(name: str | None) -> list[Engine]:
    if not name:
        # Sem token, os de ZeroGPU só devolveriam "cota esgotada" depois de uma
        # viagem inteira. Pular é mais honesto e mais rápido.
        tem_token = hf_token() is not None
        return [e for e in ENGINES if tem_token or not e.needs_token]
    achados = [e for e in ENGINES if e.name == name]
    if not achados:
        conhecidos = ", ".join(e.name for e in ENGINES)
        raise MeshBackendError(name, f"unknown engine (try: {conhecidos})")
    return achados


def hf_token() -> str | None:
    """Token da Hugging Face, se houver. Ele não é obrigatório — os motores
    padrão respondem sem conta nenhuma — mas os melhores rodam em ZeroGPU, e
    ZeroGPU dá **zero segundo** para quem chega anônimo. Com um token de conta
    gratuita eles passam a responder."""
    for chave in ("NANOBRIDGE_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        valor = os.environ.get(chave)
        if valor:
            return valor.strip()
    caminho = Path.home() / ".cache/huggingface/token"
    if caminho.exists():
        conteudo = caminho.read_text().strip()
        if conteudo:
            return conteudo
    return None


def _client(space: str):
    try:
        from gradio_client import Client
    except ImportError as exc:
        raise Mesh3DUnavailableError("gradio_client") from exc
    token = hf_token()
    return Client(space, verbose=False, hf_token=token) if token else Client(space, verbose=False)


def _collect(resposta) -> list[str]:
    """Acha os caminhos de malha em qualquer formato de resposta do Gradio.

    Cada Space devolve uma forma diferente: tupla de caminhos no TripoSR, lista
    com dicionário `{"value": ...}` no Hunyuan. Varrer é mais barato que manter
    um desempacotador por motor, e não quebra quando o Space muda de layout.
    """
    achados: list[str] = []

    def anda(item) -> None:
        if isinstance(item, dict):
            valor = item.get("value") or item.get("path")
            if isinstance(valor, str):
                anda(valor)
            else:
                for sub in item.values():
                    anda(sub)
        elif isinstance(item, (list, tuple)):
            for sub in item:
                anda(sub)
        elif isinstance(item, str) and item.lower().endswith((".glb", ".obj", ".ply")):
            if os.path.exists(item):
                achados.append(item)

    anda(resposta)
    # .glb antes de .obj: o GLB carrega a cor por vértice dentro do arquivo, e o
    # .obj do TripoSR vem acompanhado de um .mtl que o download não traz junto.
    achados.sort(key=lambda p: 0 if p.lower().endswith(".glb") else 1)
    return achados


def to_mesh(image: str | Path, out: str | Path, *, engine: str | None = None,
            on_stage=None) -> tuple[Path, Engine]:
    """Imagem → malha 3D. Devolve o arquivo salvo e qual motor a fez.

    Percorre a fila até um motor responder: Space público cai, entra em fila e
    volta sozinho, e travar num só transformaria uma indisponibilidade de fora
    em defeito nosso.
    """
    imagem = str(Path(image).expanduser().resolve())
    destino = Path(out).expanduser()
    destino.parent.mkdir(parents=True, exist_ok=True)

    recusas: list[str] = []
    for motor in find(engine):
        inicio = time.time()
        try:
            if on_stage:
                on_stage(motor)
            cliente = _client(motor.space)
            caminhos = _collect(motor.call(cliente, imagem))
            if not caminhos:
                raise ValueError("no mesh in the response")
            origem = caminhos[0]
            final = destino.with_suffix(Path(origem).suffix) if not destino.suffix else destino
            shutil.copy(origem, final)
            return final, motor
        except Mesh3DUnavailableError:
            raise
        except Exception as exc:
            recusas.append(
                f"{motor.name}: {type(exc).__name__}: {str(exc)[:120]} ({time.time() - inicio:.0f}s)"
            )
            continue

    if not recusas:
        raise NoMeshEngineError()
    raise MeshBackendError("3d", " | ".join(recusas))
