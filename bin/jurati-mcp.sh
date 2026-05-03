#!/usr/bin/env bash
# Wrapper for MCP clients: kills stale jurati processes before starting fresh.
# This ensures disable/enable or reconnect picks up new env vars.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
JURATI_BIN="${JURATI_BIN:-${REPO_DIR}/.venv/bin/jurati}"

export JURATI_CLIENT_SLUG="${JURATI_CLIENT_SLUG:-claude-code}"

if [[ -z "${JURATI_KNOWLEDGE_REMOTE:-}" ]]; then
  echo "JURATI_KNOWLEDGE_REMOTE is required." >&2
  echo "Run: jurati mcp-config --remote <git-url>" >&2
  exit 1
fi

if [[ ! -x "${JURATI_BIN}" ]]; then
  if command -v jurati >/dev/null 2>&1; then
    JURATI_BIN="$(command -v jurati)"
  else
    echo "Could not find jurati. Set JURATI_BIN or install Jurati first." >&2
    exit 1
  fi
fi

pkill -f "jurati serve" 2>/dev/null || true
sleep 0.3

exec "${JURATI_BIN}" serve
