"""O token que permite continuar editando a mesma imagem.

Por dentro é a lista de metadados do Gemini (`cid`, `rid`, `rcid`). O que **não**
pode acontecer é ele sair daqui parecendo JSON: a camada MCP pré-interpreta todo
argumento de texto que seja JSON válido, então um token `["c_1", "r_2", null]`
chegava ao servidor como lista e era recusado na validação — a edição em várias
rodadas simplesmente não funcionava pelo MCP, só pelo CLI.

Daí o envelope: base64url com um prefixo curto. Não parece JSON, não tem `"` nem
`[`, sobrevive a linha de comando, a variável de ambiente e a URL.
"""

from __future__ import annotations

import base64
import binascii
import json

PREFIX = "nb1_"


def encode(metadata: list | None) -> str | None:
    if not metadata:
        return None
    raw = json.dumps(metadata, separators=(",", ":")).encode()
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str | None) -> list | None:
    """Aceita o envelope novo e o JSON cru que a versão anterior entregava."""
    if not token:
        return None
    text = token.strip()
    if text.startswith(PREFIX):
        body = text[len(PREFIX):]
        padded = body + "=" * (-len(body) % 4)
        try:
            text = base64.urlsafe_b64decode(padded.encode()).decode()
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, list) else None
