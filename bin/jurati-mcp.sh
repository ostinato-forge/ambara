#!/usr/bin/env bash
# Wrapper for Claude Code MCP: kills stale jurati processes before starting fresh.
# This ensures disable/enable or reconnect picks up new env vars.

export JURATI_CLIENT_SLUG="claude-code"
export JURATI_KNOWLEDGE_REMOTE="${JURATI_KNOWLEDGE_REMOTE:-git@github.com:eparenti/jurati-knowledge.git}"

pkill -f "jurati serve" 2>/dev/null
sleep 0.3

exec /home/eparenti/jurati/.venv/bin/jurati serve
