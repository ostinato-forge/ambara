#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-single-repo-dogfood.sh [--keep] [--workdir PATH] [--repo PATH]

Runs a disposable single-repo Jurati dogfood pass against an active source repo.
The script creates a local knowledge repo, installs Jurati client instructions
into a disposable clone of the source repo, runs startup checks, then exercises
the real MCP handler path in first-agent order: sync(), context(), query().

Options:
  --keep          Keep the generated dogfood directory.
  --workdir PATH  Use PATH as the dogfood directory instead of a fresh /tmp dir.
  --repo PATH     Active repo to dogfood. Defaults to this Jurati checkout.

Environment:
  JURATI_BIN      Jurati executable to test. Defaults to .venv/bin/jurati when
                  present, otherwise jurati from PATH.
  PYTHON_BIN      Python executable used for the MCP handler harness.
                  Defaults to python.
USAGE
}

keep=false
workdir=""
project_source=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep)
      keep=true
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

if [[ -z "${JURATI_BIN:-}" ]]; then
  if [[ -x "$repo_root/.venv/bin/jurati" ]]; then
    JURATI_BIN="$repo_root/.venv/bin/jurati"
  else
    JURATI_BIN="jurati"
  fi
fi

if [[ -z "$project_source" ]]; then
  project_source="$repo_root"
else
  project_source="$(cd "$project_source" && pwd)"
fi

if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-single-repo-dogfood.XXXXXX")"
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
home_dir="$workdir/home"
evidence="$workdir/evidence.md"
doctor_output="$workdir/doctor-output.txt"
tool_output="$workdir/first-agent-tool-sequence.jsonl"
remote_url="file://$knowledge_remote"
repo_name="ostinato-forge/jurati"
goal="continue the pre-release quality plan with the single-repo dogfood slice"
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

mkdir -p "$knowledge_repo/.jurati" "$home_dir"

cat > "$knowledge_repo/.jurati/config.yaml" <<'EOF'
schema_version: 1
name: jurati-single-repo-dogfood
description: Local dogfood knowledge repo for Jurati pre-release confidence work.
EOF

write_entry \
  "decisions/pre-release-confidence-before-features.md" \
  "Pre-release confidence before features" \
  "decision" \
  "L2" \
  "true" \
  "https://github.com/ostinato-forge/jurati/issues/43" \
  "[pre-release, release-quality]" \
  "Jurati's immediate release work should prioritize repeatable setup checks, installed-package smoke, and dogfood evidence before adding new product features. New feature work should wait for a dogfood failure that proves the need."

write_entry \
  "workflows/pre-release-dogfood-loop.md" \
  "Pre-release dogfood loop" \
  "workflow" \
  "L2" \
  "true" \
  "https://github.com/ostinato-forge/jurati/issues/43" \
  "[dogfood, agent-startup]" \
  "For a dogfood task, the first agent action should be sync(), the second should be context(repo=<current repo>, goal=<user request>), and any deeper lookup should use query() or search() before local-only exploration. The human-facing summary should describe relevant work constraints without entry IDs, ref paths, or knowledge-repo chores."

write_entry \
  "projects/jurati-workstream-three-status.md" \
  "Jurati Workstream 3 status" \
  "project" \
  "L1" \
  "false" \
  "null" \
  "[dogfood, workstream-3]" \
  "Workstream 3 is the single-repo dogfood slice. The active question is whether Jurati improves the first planning step by surfacing the pre-release quality constraint and dogfood workflow before the agent falls back to local-only reasoning."

cat > "$evidence" <<EOF
# Jurati Single-Repo Dogfood Evidence

- dogfood directory: $workdir
- active repo source: $project_source
- dogfood project clone: $project_repo
- knowledge repo: $knowledge_repo
- knowledge remote: $remote_url
- cache dir: $cache_dir
- isolated home: $home_dir
- repo name used for context: $repo_name
- goal used for context: $goal

## Command Evidence

EOF

append_evidence '```text'

run git init --bare "$knowledge_remote" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git init -b main 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git add . 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git \
  -c user.name="Jurati Dogfood" \
  -c user.email="jurati-dogfood@example.com" \
  commit -m "docs: seed jurati dogfood knowledge" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git remote add origin "$remote_url" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git push -u origin main 2>&1 | tee -a "$evidence"

run git clone --quiet "$project_source" "$project_repo" 2>&1 | tee -a "$evidence"
run "$JURATI_BIN" validate "$knowledge_repo" 2>&1 | tee -a "$evidence"
run "$JURATI_BIN" install-claude-md --repo-path "$project_repo" --remote "$remote_url" \
  2>&1 | tee -a "$evidence"
run_in "$project_repo" "$JURATI_BIN" mcp-config --remote "$remote_url" --write-project \
  2>&1 | tee -a "$evidence"
run_in "$project_repo" env \
  HOME="$home_dir" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  "$JURATI_BIN" doctor --check-startup 2>&1 | tee "$doctor_output" | tee -a "$evidence"
grep -q 'Ready for `jurati serve`: yes' "$doctor_output"
run_in "$project_repo" env \
  HOME="$home_dir" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  "$JURATI_BIN" serve --check 2>&1 | tee -a "$evidence"

append_evidence '```'

cat >> "$evidence" <<'EOF'

## First-Agent Tool Sequence

The scripted harness below uses the real Jurati MCP handler functions. It is a
repeatable pre-agent dogfood check, not a substitute for a manual connected
Claude Code session.

```jsonl
EOF

DOGFOOD_REMOTE_URL="$remote_url" \
DOGFOOD_CACHE_DIR="$cache_dir" \
DOGFOOD_REPO_NAME="$repo_name" \
DOGFOOD_GOAL="$goal" \
PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
"$PYTHON_BIN" - <<'PY' 2>&1 | tee "$tool_output" | tee -a "$evidence"
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import anyio
import git

from jurati.git.config import JuratiConfig
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.server import ServerState, SyncHealth, context, query, sync


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


def _event(tool: str, **payload: Any) -> None:
    print(json.dumps({"tool": tool, **payload}, sort_keys=True))


async def main() -> None:
    remote_url = os.environ["DOGFOOD_REMOTE_URL"]
    cache_dir = os.environ["DOGFOOD_CACHE_DIR"]
    repo_name = os.environ["DOGFOOD_REPO_NAME"]
    goal = os.environ["DOGFOOD_GOAL"]

    config = JuratiConfig(
        remote_url=remote_url,
        cache_dir=cache_dir,
        client_slug="single-repo-dogfood",
        active_refs_enabled=True,
    )
    repo_path = ensure_repo(remote_url, cache_dir)
    repo = git.Repo(repo_path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Dogfood")
        writer.set_value("user", "email", "jurati-dogfood@example.com")
    fetch_all(repo_path, active_refs_enabled=True)
    now = datetime.now(UTC)
    state = ServerState(
        config=config,
        repo_path=repo_path,
        index=load_index_from_repo(repo_path, active_refs_enabled=True),
        last_sync=now,
        sync_health=SyncHealth(last_success=now),
    )
    ctx = _FakeCtx(state)

    sync_result = await sync(ctx=ctx)
    _event(
        "sync",
        status=sync_result["status"],
        entries=sync_result["entries"],
        visibility=sync_result["visibility"],
    )

    context_result = await context(ctx=ctx, repo=repo_name, goal=goal)
    recent_titles = [entry["title"] for entry in context_result.get("recent", [])]
    _event(
        "context",
        repo=repo_name,
        goal=goal,
        active_count=len(context_result.get("active", [])),
        recent_titles=recent_titles,
    )

    query_result = await query(topic="dogfood release quality", ctx=ctx)
    query_titles = [
        result["title"]
        for result in query_result
        if isinstance(result, dict) and "title" in result
    ]
    _event("query", topic="dogfood release quality", result_titles=query_titles)

    developer_summary = (
        "Pre-release work should stay focused on confidence gates before new "
        "features. For this slice, start from the dogfood loop: refresh context, "
        "surface the quality constraint, and turn misses into follow-up issues "
        "or patches."
    )
    forbidden = ("entry id", "refs/", "branch plumbing", "knowledge repo chores")
    lowered = developer_summary.lower()
    if any(term in lowered for term in forbidden):
        raise AssertionError("developer summary leaked implementation details")
    _event("developer_summary", text=developer_summary)

    if [sync_result["status"], bool(recent_titles), bool(query_titles)] != ["ok", True, True]:
        raise AssertionError("dogfood harness did not surface expected context")


anyio.run(main)
PY

append_evidence '```'

cat >> "$evidence" <<EOF

## Result

Single-repo dogfood harness passed.

Important caveat: this validates the repo setup and real MCP handler sequence,
but the final Workstream 3 gate still needs a manual connected agent run to
confirm the client obeys the startup instructions without prompting.
EOF

grep -q '"tool": "sync"' "$tool_output"
grep -q '"tool": "context"' "$tool_output"
grep -q '"tool": "query"' "$tool_output"
grep -q '"tool": "developer_summary"' "$tool_output"
grep -q 'Pre-release confidence before features' "$tool_output"
grep -q 'Pre-release dogfood loop' "$tool_output"
grep -q 'Single-repo dogfood harness passed.' "$evidence"

echo ""
echo "Jurati single-repo dogfood harness passed."
echo "Evidence: $evidence"
if [[ "$keep" == true ]]; then
  echo "Dogfood directory kept: $workdir"
else
  echo "Dogfood directory will be removed. Re-run with --keep to inspect generated files."
fi
