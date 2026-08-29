"""Transformar uma malha 3D em quadros 2D — o rasterizador que fecha o ciclo.

Por que um rasterizador escrito à mão, e não OpenGL: sprite pré-renderizado é
imagem pequena (64 a 256 px) e a saída precisa ser **igual em toda máquina**,
inclusive dentro de teste automatizado e de servidor MCP sem tela. OpenGL no
macOS headless depende de contexto que nem sempre existe, e o resultado varia
com driver. Aqui é NumPy puro: mesmo GLB, mesma imagem, em qualquer lugar.

A técnica é *splat* de vértice com buffer de profundidade, e não varredura de
triângulo. Rasterizar triângulo de verdade custa um laço Python por face — com
110 mil faces isso são 110 mil iterações por quadro. Subdividindo a malha até
cada aresta ficar menor que um pixel, cada vértice **é** um pixel: o desenho
inteiro vira quatro operações vetorizadas, e não sobra buraco, porque a
subdivisão garante densidade maior que a da grade.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

#: Amostras por pixel na renderização, antes de reduzir. 2 significa desenhar
#: em dobro e encolher: é o que dá borda suave sem depender de antialiasing
#: de placa de vídeo, que aqui não existe.
SUPERSAMPLE = 2

#: Direção da luz principal, no espaço da câmera: um pouco à esquerda, acima e
#: à frente. É a luz de três quartos de qualquer render de personagem.
KEY_LIGHT = (-0.45, 0.75, 0.95)

#: Piso de iluminação. Sem ele o lado escuro do personagem vira silhueta preta,
#: que num sprite de 64 px come metade da leitura da forma.
AMBIENT = 0.34


def _require(module: str, hint: str):
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        from .errors import Mesh3DUnavailableError

        raise Mesh3DUnavailableError(hint) from exc


def load_mesh(path: str | Path):
    """Carrega GLB/OBJ/PLY e devolve uma malha única, centrada e normalizada.

    Normalizar aqui, e não na hora de desenhar, é o que faz dois modelos
    diferentes (TripoSR e Hunyuan devolvem escalas distintas) renderizarem no
    mesmo tamanho de quadro.
    """
    trimesh = _require("trimesh", "trimesh")
    np = _require("numpy", "numpy")

    loaded = trimesh.load(str(path), force="scene")
    parts = list(loaded.geometry.values()) if hasattr(loaded, "geometry") else [loaded]
    parts = [p for p in parts if hasattr(p, "faces") and len(p.faces)]
    if not parts:
        from .errors import EmptyMeshError

        raise EmptyMeshError(str(path))
    mesh = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]

    # A malha sai do gerador com o eixo Y para cima mas com centro e escala
    # arbitrários; sem isto o personagem nasce fora do quadro.
    mesh.vertices = np.asarray(mesh.vertices, dtype="float64") - mesh.bounds.mean(axis=0)
    extent = float((mesh.bounds[1] - mesh.bounds[0]).max())
    if extent > 0:
        mesh.vertices = mesh.vertices / extent
    return mesh


def vertex_normals(mesh):
    """Normais por vértice, calculadas aqui em vez de pedir ao trimesh.

    Não é reinventar roda: sem SciPy instalado o trimesh avisa "unable to use
    sparse matrix, falling back" e cai num caminho lento — **60 s** nesta malha
    de 110 mil faces, contra 0,1 s aqui. E SciPy inteiro como dependência para
    somar vetor por vértice é caro demais.

    A normal da face sai do produto vetorial sem normalizar, cujo módulo vale o
    dobro da área: a ponderação por área, que é a que dá sombreado suave, já vem
    de graça na soma.
    """
    np = _require("numpy", "numpy")
    faces = np.asarray(mesh.faces)
    verts = np.asarray(mesh.vertices, dtype="float64")
    tri = verts[faces]
    face_normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])

    acumulado = np.zeros_like(verts)
    for canto in range(3):
        alvo = faces[:, canto]
        for eixo in range(3):
            acumulado[:, eixo] += np.bincount(alvo, weights=face_normal[:, eixo], minlength=len(verts))
    comprimento = np.linalg.norm(acumulado, axis=1, keepdims=True)
    comprimento[comprimento == 0] = 1.0
    return acumulado / comprimento


def vertex_colors(mesh):
    """Cor por vértice, em 0..1. Malha sem cor vira barro claro, de propósito:
    branco puro apaga o relevo, e cinza médio faz o sprite sumir no fundo."""
    np = _require("numpy", "numpy")
    visual = getattr(mesh, "visual", None)
    for attempt in ("direct", "convert"):
        try:
            source = visual if attempt == "direct" else visual.to_color()
            colors = getattr(source, "vertex_colors", None)
            if colors is not None and len(colors) == len(mesh.vertices):
                return np.asarray(colors)[:, :3].astype("float32") / 255.0
        except Exception:
            continue
    return np.full((len(mesh.vertices), 3), 0.80, dtype="float32")


def densify(mesh, samples: int, *, seed: int = 20260829):
    """Nuvem de pontos densa o bastante para cobrir a grade de pixels.

    Devolve (posições, normais, cores). O método é amostragem da superfície
    ponderada por área: sorteia faces proporcionalmente ao tamanho delas e um
    ponto baricêntrico dentro de cada uma, interpolando normal e cor.

    Duas alternativas foram medidas nesta mesma malha (110 mil faces, quadro de
    384 px) e descartadas: `subdivide_to_size` levou **87 s**, e a subdivisão em
    rodadas do trimesh levou **60 s**. Esta leva menos de um segundo, porque não
    reconstrói topologia — e topologia é justamente o que o desenho por splat
    joga fora.

    A semente é fixa de propósito: mesmo GLB, mesmos pixels, inclusive em teste.
    """
    np = _require("numpy", "numpy")

    faces = np.asarray(mesh.faces)
    verts = np.asarray(mesh.vertices, dtype="float64")
    normals = vertex_normals(mesh)
    colors = np.asarray(vertex_colors(mesh), dtype="float64")

    # Seis amostras por pixel: metade da superfície de um modelo fechado aponta
    # para longe da câmera e é descartada pelo buffer de profundidade, e a
    # amostragem é aleatória, então a margem evita o buraco de um pixel só.
    alvo = int(samples * 6)
    if alvo <= len(verts):
        return verts, normals, colors

    tri = verts[faces]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2.0
    total = float(area.sum())
    if total <= 0:
        return verts, normals, colors

    rng = np.random.default_rng(seed)
    escolha = rng.choice(len(faces), size=alvo, p=area / total)
    # Baricêntrica uniforme pelo truque da raiz: sem ele os pontos se acumulam
    # num canto do triângulo e a densidade fica irregular.
    r1, r2 = rng.random(alvo), rng.random(alvo)
    raiz = np.sqrt(r1)
    peso = np.stack([1.0 - raiz, raiz * (1.0 - r2), raiz * r2], axis=1)[:, :, None]

    canto = faces[escolha]
    pontos = (verts[canto] * peso).sum(axis=1)
    normal_amostra = (normals[canto] * peso).sum(axis=1)
    cor_amostra = (colors[canto] * peso).sum(axis=1)

    # Os vértices originais entram junto: eles são a silhueta, e perder a ponta
    # de um dedo por sorteio é exatamente o que se nota num sprite pequeno.
    pontos = np.concatenate([verts, pontos])
    normal_amostra = np.concatenate([normals, normal_amostra])
    cor_amostra = np.concatenate([colors, cor_amostra])

    comprimento = np.linalg.norm(normal_amostra, axis=1, keepdims=True)
    comprimento[comprimento == 0] = 1.0
    return pontos, normal_amostra / comprimento, cor_amostra


def _shade(normals_rot, colors, np):
    light = np.asarray(KEY_LIGHT, dtype="float64")
    light = light / np.linalg.norm(light)
    dot = normals_rot @ light
    # Meio-lambert (Valve): mapeia -1..1 para 0..1 em vez de cortar em zero. Num
    # sprite pequeno isso importa mais que fisicamente correto — a face oposta à
    # luz continua legível em vez de virar mancha.
    wrapped = 0.5 + 0.5 * dot
    lit = AMBIENT + (1.0 - AMBIENT) * wrapped
    rim = np.clip(dot, 0.0, 1.0) ** 3 * 0.18  # brilho de borda: destaca a silhueta
    return np.clip(colors * lit[:, None] + rim[:, None], 0.0, 1.0)


def _rotation(np, yaw: float, pitch: float):
    ya, pa = math.radians(yaw), math.radians(pitch)
    rot_y = np.array([[math.cos(ya), 0, math.sin(ya)], [0, 1, 0], [-math.sin(ya), 0, math.cos(ya)]])
    rot_x = np.array([[1, 0, 0], [0, math.cos(pa), -math.sin(pa)], [0, math.sin(pa), math.cos(pa)]])
    return rot_y @ rot_x


def common_framing(verts, angles, *, pitch: float = 0.0, zoom: float = 0.92):
    """A escala e o centro que servem a TODOS os ângulos da volta.

    Enquadrar quadro a quadro parece melhor isolado e é errado no jogo: o
    personagem encolhe e cresce ao virar, porque de braços abertos ele é largo
    de frente e estreito de lado. Um enquadramento só, medido na união de todos
    os ângulos, mantém o tamanho constante — que é o que a animação precisa.
    """
    np = _require("numpy", "numpy")
    limites = []
    for yaw in angles:
        pos = np.asarray(verts) @ _rotation(np, yaw, pitch).T
        limites.append([pos[:, 0].min(), pos[:, 0].max(), pos[:, 1].min(), pos[:, 1].max()])
    limites = np.asarray(limites)
    x0, x1 = float(limites[:, 0].min()), float(limites[:, 1].max())
    y0, y1 = float(limites[:, 2].min()), float(limites[:, 3].max())
    span = max(x1 - x0, y1 - y0) or 1.0
    return {"span": span, "cx": (x0 + x1) / 2.0, "cy": (y0 + y1) / 2.0, "zoom": zoom}


def render_view(mesh_or_arrays, *, yaw: float = 0.0, pitch: float = 0.0, size: int = 192,
                zoom: float = 0.92, framing: dict | None = None,
                supersample: int = SUPERSAMPLE) -> Image.Image:
    """Um quadro, em projeção ortográfica, com fundo transparente.

    Ortográfica e não perspectiva porque sprite pré-renderizado de jogo 2D é
    isso: o personagem não pode mudar de proporção ao atravessar a tela.

    Aceita a malha ou a tupla (vértices, normais, cores) já adensada — reusar a
    tupla é o que faz a volta de oito quadros custar oito vezes o desenho, e não
    oito vezes a subdivisão.
    """
    np = _require("numpy", "numpy")

    if isinstance(mesh_or_arrays, tuple):
        verts, normals, colors = mesh_or_arrays
    else:
        verts, normals, colors = densify(mesh_or_arrays, (size * supersample) ** 2)

    grade = size * max(supersample, 1)
    rot = _rotation(np, yaw, pitch)
    pos = np.asarray(verts) @ rot.T
    nrm = np.asarray(normals) @ rot.T
    rgb = _shade(nrm, np.asarray(colors, dtype="float64"), np)

    if framing is None:
        framing = common_framing(verts, [yaw], pitch=pitch, zoom=zoom)
    escala = (grade - 1) * framing["zoom"] / framing["span"]
    px = np.rint((pos[:, 0] - framing["cx"]) * escala + grade / 2.0).astype("int64")
    py = np.rint(grade / 2.0 - (pos[:, 1] - framing["cy"]) * escala).astype("int64")

    dentro = (px >= 0) & (px < grade) & (py >= 0) & (py < grade)
    px, py, z, rgb = px[dentro], py[dentro], pos[dentro, 2], rgb[dentro]
    # Buffer de profundidade sem laço: escreve do mais longe para o mais perto,
    # então o último a escrever cada pixel é o mais próximo da câmera.
    ordem = np.argsort(z, kind="stable")
    plano = py[ordem] * grade + px[ordem]
    buffer = np.zeros((grade * grade, 4), dtype="float32")
    buffer[plano, :3] = rgb[ordem]
    buffer[plano, 3] = 1.0
    quadro = Image.fromarray((buffer.reshape(grade, grade, 4) * 255).astype("uint8"), "RGBA")
    if grade != size:
        # LANCZOS na imagem RGBA multiplica cor por alfa na borda e escurece o
        # contorno. Reduzir cor e alfa juntos com BOX evita isso e é o que dá a
        # borda limpa que um sprite recortado precisa.
        quadro = quadro.resize((size, size), Image.Resampling.BOX)
    return quadro


def turntable(mesh, *, frames: int = 8, size: int = 192, pitch: float = 0.0,
              start: float = 0.0, zoom: float = 0.92,
              supersample: int = SUPERSAMPLE) -> list[Image.Image]:
    """As N direções de um sprite pré-renderizado, girando no eixo vertical.

    Oito quadros é o padrão dos jogos isométricos clássicos: 45° por direção.
    `pitch` inclina a câmera — 30° dá a vista isométrica de verdade.
    """
    passo = 360.0 / max(frames, 1)
    angulos = [start + i * passo for i in range(frames)]
    arrays = densify(mesh, (size * max(supersample, 1)) ** 2)
    enquadramento = common_framing(arrays[0], angulos, pitch=pitch, zoom=zoom)
    return [
        render_view(arrays, yaw=a, pitch=pitch, size=size, framing=enquadramento,
                    supersample=supersample)
        for a in angulos
    ]
