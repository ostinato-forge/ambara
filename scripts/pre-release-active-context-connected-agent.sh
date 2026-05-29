#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-active-context-connected-agent.sh [--keep] [--workdir PATH] [--repo PATH] [--skip-claude]

Runs the connected-agent active-context gate for issue #90. The script creates a
disposable knowledge repo and project clone, enables active refs through
repo-owned policy, seeds one active handoff from a simulated teammate, then runs
Claude Code against the project-local MCP config.

The gate passes only if:
  - active refs are enabled by project config, not by a hidden user preference
  - startup context sees the seeded active handoff
  - Claude Code calls startup() before record()
  - Claude Code records the requested handoff through active context
  - the visible answer does not expose entry IDs, refs, branch names, expiry
    mechanics, raw MCP JSON, or knowledge-repo chores

Options:
  --keep          Keep the generated test directory.
  --workdir PATH  Use PATH as the test directory instead of a fresh /tmp dir.
  --repo PATH     Active repo to clone. Defaults to this Jurati checkout.
  --skip-claude   Prepare and verify the fixture without running Claude Code.

Environment:
  JURATI_BIN      Jurati executable to test. Defaults to .venv/bin/jurati when
                  present, otherwise jurati from PATH.
  PYTHON_BIN      Python executable used for local parsing. Defaults to python.
  CLAUDE_BIN      Claude Code executable. Defaults to claude.
USAGE
}

keep=false
skip_claude=false
workdir=""
project_source=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep)
      keep=true
      shift
      ;;
    --skip-claude)
      skip_claude=true
      shift
      ;;
    --workdir)
      if [[ $# -lt 2 ]]; then
        echo "error: --workdir requires a path" >&2
        exit 2
      fi
      workdir="$2"
      shift 2
      ;;
    --repo)
      if [[ $# -lt 2 ]]; then
        echo "error: --repo requires a path" >&2
        exit 2
      fi
      project_source="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

if [[ -z "${JURATI_BIN:-}" ]]; then
  if [[ -x "$repo_root/.venv/bin/jurati" ]]; then
    JURATI_BIN="$repo_root/.venv/bin/jurati"
  else
    JURATI_BIN="jurati"
  fi
fi
if [[ "$JURATI_BIN" != /* ]]; then
  JURATI_BIN="$(command -v "$JURATI_BIN")"
fi

if [[ -z "$project_source" ]]; then
  project_source="$repo_root"
else
  project_source="$(cd "$project_source" && pwd)"
fi

if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-active-context-gate.XXXXXX")"
else
  mkdir -p "$workdir"
  workdir="$(cd "$workdir" && pwd)"
fi

if [[ "$keep" != true ]]; then
  cleanup() {
    rm -rf "$workdir"
  }
  trap cleanup EXIT
fi

knowledge_repo="$workdir/jurati-knowledge"
knowledge_remote="$workdir/jurati-knowledge.git"
project_repo="$workdir/project-repo"
cache_dir="$workdir/cache"
writer_cache_dir="$workdir/writer-cache"
remote_url="file://$knowledge_remote"
evidence="$workdir/evidence.md"
doctor_output="$workdir/doctor-output.txt"
startup_json="$workdir/startup.json"
claude_stream="$workdir/claude-stream.jsonl"
claude_score="$workdir/claude-score.json"
server_name_file="$workdir/server-name.txt"
active_refs_before="$workdir/active-refs-before.txt"
active_refs_after="$workdir/active-refs-after.txt"
repo_name="ostinato-forge/jurati"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

run() {
  echo "+ $*"
  "$@"
}

run_in() {
  local dir="$1"
  shift
  echo "+ (cd $dir && $*)"
  (cd "$dir" && "$@")
}

append_evidence() {
  printf '%s\n' "$*" >> "$evidence"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

write_entry() {
  local path="$1"
  local title="$2"
  local type="$3"
  local level="$4"
  local review_required="$5"
  local review_pr="$6"
  local tags="$7"
  local body="$8"

  mkdir -p "$(dirname "$knowledge_repo/$path")"
  cat > "$knowledge_repo/$path" <<EOF
---
schema_version: 2
id: $(basename "$path" .md)
title: $title
type: $type
level: $level
status: active
created_at: $timestamp
updated_at: $timestamp
expires_at: null
projects: [jurati]
tags: $tags
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: $review_required
  pr: $review_pr
visibility: internal
---

$body
EOF
}

require_command "$PYTHON_BIN"
require_command "$JURATI_BIN"
require_command git
if [[ "$skip_claude" != true ]]; then
  require_command "$CLAUDE_BIN"
fi

mkdir -p "$knowledge_repo/.jurati"

cat > "$knowledge_repo/.jurati/config.yaml" <<'EOF'
schema_version: 1
name: jurati-active-context-gate
description: Local knowledge repo for the active-context connected-agent gate.
EOF

write_entry \
  "workflows/active-context-handoff-protocol.md" \
  "Active context handoff protocol" \
  "workflow" \
  "L2" \
  "true" \
  "https://github.com/ostinato-forge/jurati/issues/90" \
  "[active-context, test-gate]" \
  "Short-lived handoffs may be recorded as active context only when the project explicitly opts in through repo-owned policy. Developer-facing replies should confirm the work in one sentence without exposing entry IDs, ref paths, branch names, expiry mechanics, raw tool JSON, or knowledge-repo chores."

write_entry \
  "projects/issue-90-team-loop-status.md" \
  "Issue 90 team loop status" \
  "project" \
  "L1" \
  "false" \
  "null" \
  "[issue-90, active-context]" \
  "The current gate is an active-context connected-agent pass. The agent should call startup before local exploration, notice active handoff context when present, and save a new handoff without leaking storage details in the terminal reply."

cat > "$evidence" <<EOF
# Active Context Connected-Agent Gate Evidence

- generated at: $timestamp
- issue: https://github.com/ostinato-forge/jurati/issues/90
- gate directory: $workdir
- active repo source: $project_source
- project clone: $project_repo
- knowledge remote: $remote_url
- cache dir: $cache_dir
- writer cache dir: $writer_cache_dir
- command under test: $JURATI_BIN
- repo name used for startup: $repo_name

## Setup Commands

\`\`\`text
EOF

run git init --bare "$knowledge_remote" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git init -b main 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git add . 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git \
  -c user.name="Jurati Test Gate" \
  -c user.email="jurati-test-gate@example.com" \
  commit -m "docs: seed active context gate knowledge" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git remote add origin "$remote_url" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git push -u origin main 2>&1 | tee -a "$evidence"

run git clone --quiet "$project_source" "$project_repo" 2>&1 | tee -a "$evidence"
mkdir -p "$project_repo/.jurati"
cat > "$project_repo/.jurati/config.yaml" <<EOF
schema_version: 1
knowledge_remote: $remote_url
active_refs:
  enabled: true
  ttl_hours: 6
EOF

run "$JURATI_BIN" validate "$knowledge_repo" 2>&1 | tee -a "$evidence"
run "$JURATI_BIN" install-claude-md --repo-path "$project_repo" --remote "$remote_url" --v2 \
  2>&1 | tee -a "$evidence"
run_in "$project_repo" "$JURATI_BIN" mcp-config \
  --remote "$remote_url" \
  --client-slug claude-code \
  --command "$JURATI_BIN" \
  --write-project 2>&1 | tee -a "$evidence"

"$PYTHON_BIN" - "$project_repo/.mcp.json" "$cache_dir" "$server_name_file" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
cache_dir = sys.argv[2]
server_name_path = Path(sys.argv[3])
data = json.loads(config_path.read_text())
servers = data["mcpServers"]
server_name, server_config = next(iter(servers.items()))
env = server_config.setdefault("env", {})
env["JURATI_CACHE_DIR"] = cache_dir
env["JURATI_CONTEXT_DEFAULT_MODE"] = "startup"
config_path.write_text(json.dumps(data, indent=2) + "\n")
server_name_path.write_text(server_name)
PY
server_name="$(cat "$server_name_file")"
append_evidence "+ added JURATI_CACHE_DIR and startup context mode to .mcp.json"
append_evidence "+ MCP server name: $server_name"

run_in "$project_repo" env \
  JURATI_CACHE_DIR="$cache_dir" \
  "$JURATI_BIN" doctor --check-startup --team 2>&1 | tee "$doctor_output" | tee -a "$evidence"
grep -q 'Ready for `jurati serve`: yes' "$doctor_output"
grep -q 'active refs policy:        enabled' "$doctor_output"
grep -q 'active refs TTL:           6h' "$doctor_output"

run_in "$project_repo" env \
  JURATI_CACHE_DIR="$cache_dir" \
  "$JURATI_BIN" serve --check 2>&1 | tee -a "$evidence"

append_evidence '```'

cat >> "$evidence" <<'EOF'

## Seeded Active Context

The gate seeds one active handoff from a simulated teammate before the
connected-agent run. This verifies active refs are discovered through the same
repo-owned opt-in policy the MCP client receives.

```text
EOF

run_in "$project_repo" env \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$writer_cache_dir" \
  JURATI_ACTIVE_REFS_ENABLED=true \
  JURATI_ACTIVE_REF_TTL_HOURS=6 \
  JURATI_CLIENT_SLUG=alice-agent \
  GIT_AUTHOR_NAME="Alice Test" \
  GIT_AUTHOR_EMAIL="alice-test@example.invalid" \
  GIT_COMMITTER_NAME="Alice Test" \
  GIT_COMMITTER_EMAIL="alice-test@example.invalid" \
  "$JURATI_BIN" record \
  --type active \
  --title "Checkout session refresh handoff" \
  --projects jurati \
  --tags active-context,issue-90 \
  --content "Alice verified the checkout session refresh contract: use a 900 second refresh window and server-driven rotation policy. Bob should update release docs before the next rollout." \
  2>&1 | tee -a "$evidence"

git ls-remote "$remote_url" 'refs/heads/jurati/active/*' > "$active_refs_before"
append_evidence '```'

cat >> "$evidence" <<EOF

Active refs after seeded handoff:

\`\`\`text
$(cat "$active_refs_before")
\`\`\`

## Startup Packet Check

\`\`\`text
EOF

run_in "$project_repo" env \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  JURATI_ACTIVE_REFS_ENABLED=true \
  JURATI_ACTIVE_REF_TTL_HOURS=6 \
  "$JURATI_BIN" startup \
  --repo "$repo_name" \
  --goal "Plan the release-doc update using current handoff context." \
  --format json \
  --output "$startup_json" 2>&1 | tee -a "$evidence"

"$PYTHON_BIN" - "$startup_json" <<'PY' 2>&1 | tee -a "$evidence"
from __future__ import annotations

import json
import sys
from pathlib import Path

packet = json.loads(Path(sys.argv[1]).read_text())
entries = packet.get("entries", [])
titles = [entry.get("title", "") for entry in entries]
if "Checkout session refresh handoff" not in titles:
    raise SystemExit(f"seeded active handoff missing from startup packet: {titles!r}")
print("startup packet includes seeded active handoff")
print(f"availability={packet.get('availability')} action={packet.get('action')}")
print(f"entries={titles}")
PY
append_evidence '```'

if [[ "$skip_claude" == true ]]; then
  cat >> "$evidence" <<'EOF'

## Connected-Agent Run

Skipped by --skip-claude.
EOF
  echo "Active-context fixture prepared without Claude Code."
  echo "Evidence: $evidence"
  if [[ "$keep" == true ]]; then
    echo "Gate directory kept: $workdir"
  fi
  exit 0
fi

allowed_tools="mcp__${server_name}__startup,mcp__${server_name}__record"
prompt="We are testing the issue #90 active-context gate. Follow the project startup contract before doing anything else, but do not send me any text before the required tools finish. Then save this handoff for the next agent: Alice verified checkout session refresh must use a 900 second refresh window and server-driven rotation policy; Bob should update release docs before rollout. After saving it, reply in one short sentence about the work only."

cat >> "$evidence" <<EOF

## Connected-Agent Run

- Claude command: \`$CLAUDE_BIN -p --mcp-config .mcp.json --strict-mcp-config --setting-sources project --permission-mode dontAsk --allowedTools "$allowed_tools" --output-format stream-json --verbose --max-budget-usd 1 <prompt>\`
- Allowed tools: \`$allowed_tools\`

\`\`\`text
EOF

(
  cd "$project_repo"
  "$CLAUDE_BIN" -p \
    --mcp-config .mcp.json \
    --strict-mcp-config \
    --setting-sources project \
    --permission-mode dontAsk \
    --allowedTools "$allowed_tools" \
    --output-format stream-json \
    --verbose \
    --max-budget-usd 1 \
    "$prompt"
) 2>&1 | tee "$claude_stream" | tee -a "$evidence"

append_evidence '```'

"$PYTHON_BIN" - "$claude_stream" "$claude_score" "$server_name" <<'PY' 2>&1 | tee -a "$evidence"
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

stream_path = Path(sys.argv[1])
score_path = Path(sys.argv[2])
server_name = sys.argv[3]

tool_names: list[str] = []
text_parts: list[str] = []
result_payload: dict[str, Any] = {}

def walk(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "tool_use" and isinstance(value.get("name"), str):
            tool_names.append(value["name"])
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            text_parts.append(value["text"])
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for item in value:
            walk(item)

for raw in stream_path.read_text().splitlines():
    if not raw.strip().startswith("{"):
        continue
    event = json.loads(raw)
    if event.get("type") == "result":
        result_payload = event
        if isinstance(event.get("result"), str):
            text_parts.append(event["result"])
    walk(event)

expected_startup = f"mcp__{server_name}__startup"
expected_record = f"mcp__{server_name}__record"
if not tool_names:
    raise SystemExit("Claude stream contained no tool_use events")
if tool_names[0] != expected_startup:
    raise SystemExit(f"first tool was {tool_names[0]!r}, expected {expected_startup!r}")
if expected_record not in tool_names:
    raise SystemExit(f"record tool missing from tool sequence: {tool_names!r}")

visible_text = "\n".join(part.strip() for part in text_parts if part.strip())
forbidden_patterns = {
    "jurati": r"\bjurati\b",
    "mcp": r"\bmcp\b",
    "entry id": r"\bentry\s+id\b",
    "ref path": r"\brefs?/heads/|\bref path\b|\bactive ref\b",
    "branch": r"\bbranch(?:es)?\b",
    "expiry": r"\bexpir(?:y|es?|ation)\b|\bttl\b",
    "knowledge repo": r"\bknowledge repo\b",
    "raw json": r"\bjson\b",
    "tool name": r"\bstartup(?:\(\))?\b|\brecord(?:\()?\b|\btool calls?\b",
}
leaks = [
    label
    for label, pattern in forbidden_patterns.items()
    if re.search(pattern, visible_text, flags=re.IGNORECASE)
]
if leaks:
    raise SystemExit(f"visible reply leaked internal terms {leaks!r}: {visible_text!r}")

score = {
    "tool_sequence": tool_names,
    "visible_reply": visible_text,
    "leaks": leaks,
    "cost_usd": result_payload.get("total_cost_usd", result_payload.get("cost_usd")),
    "session_id": result_payload.get("session_id"),
}
score_path.write_text(json.dumps(score, indent=2) + "\n")
print("connected-agent scoring passed")
print(json.dumps(score, indent=2))
PY

git ls-remote "$remote_url" 'refs/heads/jurati/active/*' > "$active_refs_after"

cat >> "$evidence" <<EOF

Active refs after connected-agent run:

\`\`\`text
$(cat "$active_refs_after")
\`\`\`

## Result

Active-context connected-agent gate passed.

EOF

grep -q "startup packet includes seeded active handoff" "$evidence"
grep -q "connected-agent scoring passed" "$evidence"
grep -q "Active-context connected-agent gate passed." "$evidence"

echo ""
echo "Active-context connected-agent gate passed."
echo "Evidence: $evidence"
echo "Claude stream: $claude_stream"
echo "Score: $claude_score"
if [[ "$keep" == true ]]; then
  echo "Gate directory kept: $workdir"
fi
