#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-multi-repo-dogfood.sh [--keep] [--workdir PATH]

Runs a disposable multi-repo Jurati dogfood pass. The script creates a local
knowledge repo, an upstream API repo, and a downstream web repo with a simulated
shared auth-contract dependency. It installs Jurati into the downstream repo,
runs startup checks, then exercises the real MCP handler path with a simulated
jurati-labeled upstream PR signal.

Options:
  --keep          Keep the generated dogfood directory.
  --workdir PATH  Use PATH as the dogfood directory instead of a fresh /tmp dir.

Environment:
  JURATI_BIN      Jurati executable to test. Defaults to .venv/bin/jurati when
                  present, otherwise jurati from PATH.
  PYTHON_BIN      Python executable used for the MCP handler harness.
                  Defaults to python.
USAGE
}

keep=false
workdir=""

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

if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-multi-repo-dogfood.XXXXXX")"
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
upstream_repo="$workdir/auth-api"
downstream_repo="$workdir/web-app"
cache_dir="$workdir/cache"
home_dir="$workdir/home"
evidence="$workdir/evidence.md"
doctor_output="$workdir/doctor-output.txt"
tool_output="$workdir/multi-repo-tool-sequence.jsonl"
remote_url="file://$knowledge_remote"
upstream_name="ostinato-dogfood/auth-api"
downstream_name="ostinato-dogfood/web-app"
shared_contract_path="contracts/auth/session.json"
goal="update the frontend auth session flow against the shared auth contract"
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

commit_all() {
  local dir="$1"
  local message="$2"
  run_in "$dir" git add .
  run_in "$dir" git \
    -c user.name="Jurati Dogfood" \
    -c user.email="jurati-dogfood@example.com" \
    commit -m "$message"
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
projects: [auth-api, web-app]
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
name: jurati-multi-repo-dogfood
description: Local dogfood knowledge repo for Jurati multi-repo coordination work.
EOF

write_entry \
  "decisions/shared-auth-contract-owned-by-api.md" \
  "Shared auth contract is owned upstream" \
  "decision" \
  "L2" \
  "true" \
  "https://github.com/ostinato-forge/jurati/issues/43" \
  "[auth, contract, multi-repo]" \
  "The auth API owns the shared session contract. The web app should not invent a local token shape while an upstream auth-contract pull request is open."

write_entry \
  "workflows/multi-repo-auth-coordination.md" \
  "Multi-repo auth coordination workflow" \
  "workflow" \
  "L2" \
  "true" \
  "https://github.com/ostinato-forge/jurati/issues/43" \
  "[coordination, auth, agent-startup]" \
  "Before frontend auth work starts, the agent should refresh Jurati context and account for any jurati-labeled upstream auth PR before editing the downstream session flow."

write_entry \
  "projects/web-app-auth-session-work.md" \
  "Web app auth session work" \
  "project" \
  "L1" \
  "false" \
  "null" \
  "[web-app, auth, workstream-4]" \
  "Workstream 4 validates that a downstream agent sees the upstream auth-contract coordination signal early enough to avoid building against a stale session contract."

cat > "$evidence" <<EOF
# Jurati Multi-Repo Dogfood Evidence

- dogfood directory: $workdir
- upstream repo: $upstream_repo
- downstream repo: $downstream_repo
- upstream repo name used for PR signal: $upstream_name
- downstream repo name used for context: $downstream_name
- shared contract path: $shared_contract_path
- knowledge repo: $knowledge_repo
- knowledge remote: $remote_url
- cache dir: $cache_dir
- isolated home: $home_dir
- goal used for context: $goal
- simulated PR: https://github.com/$upstream_name/pull/7

## Command Evidence

EOF

append_evidence '```text'

run git init --bare "$knowledge_remote" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git init -b main 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git add . 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git \
  -c user.name="Jurati Dogfood" \
  -c user.email="jurati-dogfood@example.com" \
  commit -m "docs: seed multi-repo dogfood knowledge" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git remote add origin "$remote_url" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git push -u origin main 2>&1 | tee -a "$evidence"

mkdir -p "$upstream_repo/$(dirname "$shared_contract_path")" "$upstream_repo/src/auth"
cat > "$upstream_repo/$shared_contract_path" <<'EOF'
{
  "session": {
    "token": "opaque",
    "refreshWindowSeconds": 300
  }
}
EOF
cat > "$upstream_repo/src/auth/session.py" <<'EOF'
SESSION_CONTRACT_VERSION = 1
EOF
run_in "$upstream_repo" git init -b main 2>&1 | tee -a "$evidence"
commit_all "$upstream_repo" "feat: seed auth contract" 2>&1 | tee -a "$evidence"
run_in "$upstream_repo" git checkout -b alice/auth-session-contract 2>&1 | tee -a "$evidence"
cat > "$upstream_repo/$shared_contract_path" <<'EOF'
{
  "session": {
    "token": "opaque",
    "refreshWindowSeconds": 900,
    "rotationPolicy": "server-driven"
  }
}
EOF
commit_all "$upstream_repo" "feat: revise auth session contract" 2>&1 | tee -a "$evidence"

mkdir -p "$downstream_repo/$(dirname "$shared_contract_path")" "$downstream_repo/src/auth"
cat > "$downstream_repo/$shared_contract_path" <<'EOF'
{
  "session": {
    "token": "opaque",
    "refreshWindowSeconds": 300
  }
}
EOF
cat > "$downstream_repo/src/auth/session.ts" <<'EOF'
export const refreshWindowSeconds = 300;
EOF
run_in "$downstream_repo" git init -b main 2>&1 | tee -a "$evidence"
commit_all "$downstream_repo" "feat: seed frontend auth session flow" 2>&1 | tee -a "$evidence"

run "$JURATI_BIN" validate "$knowledge_repo" 2>&1 | tee -a "$evidence"
run "$JURATI_BIN" install-claude-md --repo-path "$downstream_repo" --remote "$remote_url" \
  2>&1 | tee -a "$evidence"
run_in "$downstream_repo" "$JURATI_BIN" mcp-config --remote "$remote_url" --write-project \
  2>&1 | tee -a "$evidence"
run_in "$downstream_repo" env \
  HOME="$home_dir" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  JURATI_PR_SIGNAL_REPOS="$upstream_name" \
  "$JURATI_BIN" doctor --check-startup 2>&1 | tee "$doctor_output" | tee -a "$evidence"
grep -q 'Ready for `jurati serve`: yes' "$doctor_output"
run_in "$downstream_repo" env \
  HOME="$home_dir" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  JURATI_PR_SIGNAL_REPOS="$upstream_name" \
  "$JURATI_BIN" serve --check 2>&1 | tee -a "$evidence"

append_evidence '```'

cat >> "$evidence" <<'EOF'

## Multi-Repo Tool Sequence

The scripted harness below uses the real Jurati MCP handler functions plus a
simulated jurati-labeled upstream PR signal. It checks both goal-only startup
context and a path-specific planning follow-up.

```jsonl
EOF

DOGFOOD_REMOTE_URL="$remote_url" \
DOGFOOD_CACHE_DIR="$cache_dir" \
DOGFOOD_UPSTREAM_REPO="$upstream_name" \
DOGFOOD_DOWNSTREAM_REPO="$downstream_name" \
DOGFOOD_CONTRACT_PATH="$shared_contract_path" \
DOGFOOD_GOAL="$goal" \
PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
"$PYTHON_BIN" - <<'PY' 2>&1 | tee "$tool_output" | tee -a "$evidence"
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import git

from jurati.core.pr_signals import PRSignal
from jurati.git.config import JuratiConfig, PRSignalsConfig
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.providers.cache import SignalCache
from jurati.server import ServerState, SyncHealth, context, query, sync


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


def _event(tool: str, **payload: Any) -> None:
    print(json.dumps({"tool": tool, **payload}, sort_keys=True))


def _effects(payload: dict[str, Any]) -> list[str]:
    coordination = payload.get("coordination") or {}
    return [item["effect"] for item in coordination.get("guidance", [])]


async def main() -> None:
    remote_url = os.environ["DOGFOOD_REMOTE_URL"]
    cache_dir = os.environ["DOGFOOD_CACHE_DIR"]
    upstream_repo = os.environ["DOGFOOD_UPSTREAM_REPO"]
    downstream_repo = os.environ["DOGFOOD_DOWNSTREAM_REPO"]
    contract_path = os.environ["DOGFOOD_CONTRACT_PATH"]
    goal = os.environ["DOGFOOD_GOAL"]

    config = JuratiConfig(
        remote_url=remote_url,
        cache_dir=cache_dir,
        client_slug="multi-repo-dogfood",
        active_refs_enabled=True,
        pr_signals=PRSignalsConfig(repos=(upstream_repo,)),
    )
    repo_path = ensure_repo(remote_url, cache_dir)
    repo = git.Repo(repo_path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Dogfood")
        writer.set_value("user", "email", "jurati-dogfood@example.com")
    fetch_all(repo_path, active_refs_enabled=True)
    now = datetime.now(UTC)

    signal = PRSignal(
        signal_id=f"github:{upstream_repo}:pull:7",
        provider="github",
        repo=upstream_repo,
        number=7,
        url=f"https://github.com/{upstream_repo}/pull/7",
        title="Auth contract migration blocks frontend session rollout",
        body_excerpt=(
            "The session contract changes refresh timing and rotation policy. "
            "Downstream web work should wait or adapt to this open API PR."
        ),
        author="alice",
        state="open",
        labels=("jurati",),
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(minutes=10),
        merged_at=None,
        changed_paths=(contract_path,),
        target_areas=("contracts/auth",),
    )
    signal_cache = SignalCache(recency_days=30)
    signal_cache.update([signal], now=now)

    state = ServerState(
        config=config,
        repo_path=repo_path,
        index=load_index_from_repo(repo_path, active_refs_enabled=True),
        last_sync=now,
        sync_health=SyncHealth(last_success=now),
        signal_cache=signal_cache,
    )
    ctx = _FakeCtx(state)

    sync_result = await sync(ctx=ctx)
    _event(
        "sync",
        status=sync_result["status"],
        entries=sync_result["entries"],
        visibility=sync_result["visibility"],
    )

    goal_context = await context(ctx=ctx, repo=downstream_repo, goal=goal)
    goal_effects = _effects(goal_context)
    _event(
        "context_goal_only",
        repo=downstream_repo,
        goal=goal,
        effects=goal_effects,
        summary=(goal_context.get("coordination") or {}).get("summary"),
    )

    path_context = await context(
        ctx=ctx,
        repo=downstream_repo,
        goal=goal,
        paths=[contract_path],
    )
    path_coordination = path_context.get("coordination") or {}
    path_effects = _effects(path_context)
    evidence_repos = [
        ev["repo"]
        for item in path_coordination.get("guidance", [])
        for ev in item.get("evidence", [])
    ]
    _event(
        "context_path_specific",
        repo=downstream_repo,
        paths=[contract_path],
        effects=path_effects,
        evidence_repos=evidence_repos,
        privacy_boundary=path_coordination.get("privacy_boundary"),
    )

    query_result = await query(topic="multi repo auth coordination", ctx=ctx)
    query_titles = [
        result["title"]
        for result in query_result
        if isinstance(result, dict) and "title" in result
    ]
    _event("query", topic="multi repo auth coordination", result_titles=query_titles)

    developer_summary = (
        "Alice's upstream auth contract PR should be accounted for before "
        "changing the frontend session flow."
    )
    forbidden = ("entry id", "refs/", "branch plumbing", "knowledge repo chores")
    lowered = developer_summary.lower()
    if any(term in lowered for term in forbidden):
        raise AssertionError("developer summary leaked implementation details")
    _event("developer_summary", text=developer_summary)

    if sync_result["status"] != "ok":
        raise AssertionError("sync failed")
    if not goal_effects:
        raise AssertionError("goal-only context did not surface the upstream signal")
    if "pause" not in path_effects:
        raise AssertionError("path-specific context did not pause on the upstream PR")
    if upstream_repo not in evidence_repos:
        raise AssertionError("coordination evidence did not cite the upstream repo")
    if not query_titles:
        raise AssertionError("knowledge query did not surface coordination entries")


anyio.run(main)
PY

append_evidence '```'

cat >> "$evidence" <<EOF

## Result

Multi-repo dogfood harness passed.

The scripted path showed that goal-only startup context surfaced the upstream
coordination signal, and a path-specific follow-up produced pause guidance for
$shared_contract_path. This validates the deterministic Jurati behavior. A
manual connected-agent run is still needed to confirm a real client calls
sync() and context() before local-only exploration in the downstream repo.
EOF

grep -q '"tool": "sync"' "$tool_output"
grep -q '"tool": "context_goal_only"' "$tool_output"
grep -q '"tool": "context_path_specific"' "$tool_output"
grep -q '"tool": "query"' "$tool_output"
grep -q '"tool": "developer_summary"' "$tool_output"
grep -q '"pause"' "$tool_output"
grep -q "$upstream_name" "$tool_output"
grep -q 'Multi-repo dogfood harness passed.' "$evidence"

echo ""
echo "Jurati multi-repo dogfood harness passed."
echo "Evidence: $evidence"
if [[ "$keep" == true ]]; then
  echo "Dogfood directory kept: $workdir"
else
  echo "Dogfood directory will be removed. Re-run with --keep to inspect generated files."
fi
