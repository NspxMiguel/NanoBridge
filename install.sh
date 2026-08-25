#!/usr/bin/env bash
# NanoBridge — install the CLI, register the MCP server, install the agent skill.
#
# Safe to run again: it upgrades in place and never duplicates a registration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${NANOBRIDGE_VENV:-$ROOT/.venv}"
BIN_DIR="${NANOBRIDGE_BIN:-$HOME/.local/bin}"
SKILL_DIR="$HOME/.claude/skills/nanobanana"

say() { printf '  %s\n' "$*"; }

# --- python -----------------------------------------------------------------
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
      PY="$candidate"
      break
    fi
  fi
done
[ -n "$PY" ] || { echo "nanobridge: needs Python 3.11 or newer" >&2; exit 1; }
say "python: $($PY --version)"

# --- venv -------------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$PY" "$VENV" >/dev/null
  else
    "$PY" -m venv "$VENV"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$VENV/bin/python" --upgrade "$ROOT"
else
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet --upgrade "$ROOT"
fi
say "installed: $("$VENV/bin/nanobridge" --version)"

# --- cli on PATH ------------------------------------------------------------
# Uma instalacao pelo Homebrew ja publicou o comando em HOMEBREW_PREFIX/bin.
# Criar um segundo link aqui deixaria duas copias no PATH, e a que ganha depende
# da ordem do PATH — que e exatamente o tipo de coisa que confunde depois.
existing="$(command -v nanobridge 2>/dev/null || true)"
if [ -n "$existing" ] && [ "$existing" != "$BIN_DIR/nanobridge" ] && [ "$existing" != "$VENV/bin/nanobridge" ]; then
  say "cli: $existing ja esta no PATH (Homebrew?) — nao vou criar um segundo link"
  say "     este ambiente fica em $VENV/bin/nanobridge"
else
  mkdir -p "$BIN_DIR"
  ln -sf "$VENV/bin/nanobridge" "$BIN_DIR/nanobridge"
  say "cli: $BIN_DIR/nanobridge"
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: $BIN_DIR is not on your PATH" ;;
esac

# --- mcp server -------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  claude mcp remove nanobridge --scope user >/dev/null 2>&1 || true
  if claude mcp add nanobridge --scope user -- "$VENV/bin/nanobridge" mcp >/dev/null 2>&1; then
    say "mcp: registered with Claude Code (user scope)"
  else
    say "mcp: could not register automatically — run:"
    say "     claude mcp add nanobridge --scope user -- $VENV/bin/nanobridge mcp"
  fi
else
  say "mcp: claude CLI not found; register manually with"
  say "     claude mcp add nanobridge --scope user -- $VENV/bin/nanobridge mcp"
fi

# --- agent skill ------------------------------------------------------------
if [ -d "$ROOT/skill" ]; then
  mkdir -p "$SKILL_DIR"
  cp -f "$ROOT/skill/SKILL.md" "$SKILL_DIR/SKILL.md"
  say "skill: $SKILL_DIR/SKILL.md"
fi

echo
say "done — try:  nanobridge doctor"
