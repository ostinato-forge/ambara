#!/usr/bin/env bash
# Wrapper for MCP clients: kills stale ambara processes before starting fresh.
# This ensures disable/enable or reconnect picks up new env vars.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
AMBARA_BIN="${AMBARA_BIN:-${REPO_DIR}/.venv/bin/ambara}"

export AMBARA_CLIENT_SLUG="${AMBARA_CLIENT_SLUG:-claude-code}"

if [[ -z "${AMBARA_KNOWLEDGE_REMOTE:-}" ]]; then
  echo "AMBARA_KNOWLEDGE_REMOTE is required." >&2
  echo "Run: ambara mcp-config --remote <git-url>" >&2
  exit 1
fi

if [[ ! -x "${AMBARA_BIN}" ]]; then
  if command -v ambara >/dev/null 2>&1; then
    AMBARA_BIN="$(command -v ambara)"
  else
    echo "Could not find ambara. Set AMBARA_BIN or install Ambara first." >&2
    exit 1
  fi
fi

exec "${AMBARA_BIN}" serve
