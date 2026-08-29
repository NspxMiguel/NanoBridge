"""A documentação envelhece calada: teste que falha quando ela mente."""

import re
from pathlib import Path

import pytest

from nanobridge import cli, mcp_server

ROOT = Path(__file__).resolve().parents[1]


def subcommands() -> set[str]:
    parser = cli.build_parser()
    for action in parser._actions:
        if hasattr(action, "choices") and action.dest == "command":
            return set(action.choices)
    raise AssertionError("parser sem subcomandos")


def documented_commands(text: str) -> set[str]:
    plain = re.sub(r"<[^>]+>", "", text)
    return {m for m in re.findall(r"^nanobridge\s+([a-z-]+)", plain, flags=re.M)}


@pytest.mark.parametrize("doc", ["README.md", "skill/SKILL.md", "docs/index.html"])
def test_every_documented_command_exists(doc):
    used = documented_commands((ROOT / doc).read_text())
    unknown = used - subcommands()
    assert not unknown, f"{doc} promete comando que não existe: {sorted(unknown)}"


@pytest.mark.parametrize("doc", ["README.md", "skill/SKILL.md"])
def test_every_named_mcp_tool_exists(doc):
    text = (ROOT / doc).read_text()
    declared = {name for name in dir(mcp_server) if name.startswith(("generate_", "edit_", "cut_", "slice_"))}
    declared.add("nanobridge_status")
    named = {t for t in declared if t in text}
    assert named, f"{doc} não cita ferramenta nenhuma"
    pattern = r"`(generate_[a-z_]+|edit_image|cut_image|slice_sheet|nanobridge_status)`"
    for candidate in re.findall(pattern, text):
        assert candidate in declared, f"{doc} cita ferramenta inexistente: {candidate}"


def test_every_style_offered_in_the_docs_is_real():
    from nanobridge.core import STYLES

    for doc in ("README.md", "skill/SKILL.md"):
        text = (ROOT / doc).read_text()
        for style in re.findall(r"`(pixel|flat|cartoon|3d|realistic|sketch)`", text):
            assert style in STYLES, f"{doc} oferece estilo inexistente: {style}"


def test_the_page_and_the_package_agree_on_the_version():
    from nanobridge import __version__

    page = (ROOT / "docs/index.html").read_text()
    assert f"NanoBridge {__version__}" in page, "a página ficou numa versão antiga"


def test_the_prompting_guide_exists_and_covers_the_traps():
    """O guia é a resposta a 'como eu escrevo o prompt' — se ele encolher e
    perder as armadilhas, ele deixa de servir."""
    guide = (ROOT / "PROMPTING.md").read_text().lower()
    for trap in ("no shadow", "keep everything else identical", "converges", "loop"):
        assert trap in guide, f"o guia perdeu: {trap}"


def test_the_skill_teaches_prompting_not_just_the_command_list():
    skill = (ROOT / "skill/SKILL.md").read_text().lower()
    assert "name what you do not want" in skill
    assert "reference beats description" in skill
    assert "when the output is wrong" in skill


def test_the_readme_answers_the_login_question():
    """'Como eu faço login?' é a primeira pergunta de todo mundo."""
    readme = (ROOT / "README.md").read_text().lower()
    assert "there is no login" in readme
    assert "nanobridge setup" in readme


def test_the_docs_name_the_3d_engines_and_their_licence():
    """Quem gerou a malha não é o Nano Banana, e isso não pode ficar implícito:
    são modelos de terceiros, com licença própria, rodando em Space público."""
    from nanobridge import mesh3d

    readme = (ROOT / "README.md").read_text()
    for motor in mesh3d.ENGINES:
        assert motor.space in readme or motor.label.split(" (")[0] in readme, (
            f"o README não diz que a malha pode vir do {motor.label}"
        )
    assert "MIT" in readme


def test_the_docs_warn_that_flat_art_does_not_reconstruct():
    """A armadilha número um do 3D. Se o texto sumir, todo mundo tenta mandar
    pixel art e recebe uma placa sem entender por quê."""
    for doc in ("README.md", "skill/SKILL.md", "PROMPTING.md"):
        texto = (ROOT / doc).read_text().lower()
        assert "flat" in texto and ("depth_ratio" in texto or "volume" in texto), (
            f"{doc} não avisa que arte 2D chapada não vira malha"
        )


def test_the_docs_do_not_claim_the_image_model_makes_meshes():
    """Limite honesto, escrito de propósito: modelo de imagem não devolve
    geometria, e o dia em que a documentação sugerir isso ela virou propaganda."""
    for doc in ("README.md", "docs/index.html", "skill/SKILL.md"):
        texto = (ROOT / doc).read_text().lower()
        if "3d" not in texto:
            continue
        assert "single-image-to-3d" in texto or "reconstru" in texto, (
            f"{doc} fala de 3D sem dizer que quem faz a malha é outro modelo"
        )
