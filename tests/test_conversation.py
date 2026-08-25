"""O token de conversa não pode parecer JSON — a camada MCP pré-interpreta."""

import json

import pytest

from nanobridge import conversation

METADATA = ["c_abc123", "r_def456", "rc_ghi789", None, None, None, None, None, None, ""]


def test_round_trip():
    token = conversation.encode(METADATA)
    assert conversation.decode(token) == METADATA


def test_token_never_looks_like_json():
    """É por isso que o envelope existe: JSON válido virava lista antes de chegar."""
    token = conversation.encode(METADATA)
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(token)
    for char in '["{\'':
        assert char not in token


def test_token_survives_a_command_line_and_a_url():
    token = conversation.encode(METADATA)
    assert token.replace("-", "").replace("_", "").isalnum()


def test_empty_metadata_gives_no_token():
    assert conversation.encode(None) is None
    assert conversation.encode([]) is None


def test_decode_accepts_the_old_raw_json_form():
    """Quem guardou um token da versão anterior não pode perder a conversa."""
    assert conversation.decode(json.dumps(METADATA)) == METADATA


@pytest.mark.parametrize("bad", [None, "", "   ", "nb1_!!!!", "nb1_", "abc", "{}", '"x"', "42", "nb1_YWJj"])
def test_decode_of_junk_is_none_not_an_exception(bad):
    assert conversation.decode(bad) is None


def test_decode_is_padding_agnostic():
    token = conversation.encode(["a"])
    assert "=" not in token
    assert conversation.decode(token) == ["a"]
