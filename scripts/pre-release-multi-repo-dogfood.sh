#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-multi-repo-dogfood.sh [--keep] [--workdir PATH]

Runs a disposable multi-repo Jurati dogfood pass. The script creates a local
knowledge repo, an upstream API repo, and a downstream web repo with a simulated
shared auth-contract dependency. It imports existing project docs through
review branches, installs Jurati into the downstream repo, runs startup checks,
materializes a curation review branch from a merged signal, then exercises the
real MCP handler path with simulated jurati-labeled upstream PR signals.

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
curation_cache_dir="$workdir/curation-cache"
home_dir="$workdir/home"
evidence="$workdir/evidence.md"
doctor_output="$workdir/doctor-output.txt"
tool_output="$workdir/multi-repo-tool-sequence.jsonl"
import_output="$workdir/import-output.txt"
curation_output="$workdir/curation-output.txt"
pr_signal_fixture="$workdir/pr-signals.json"
remote_url="file://$knowledge_remote"
upstream_name="ostinato-dogfood/auth-api"
downstream_name="ostinato-dogfood/web-app"
shared_contract_path="contracts/auth/session.json"
goal="update the frontend auth session flow against the shared auth contract"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
accepted_import_timestamp="$("$PYTHON_BIN" - <<'PY'
from __future__ import annotations

from datetime import UTC, datetime, timedelta

print((datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"
auth_import_branch="jurati/import-docs-auth-contract"
web_import_branch="jurati/import-docs-web-context"
curation_branch="jurati/curation/dogfood-import-loop"

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

accept_import_branch() {
  local branch="$1"
  local review_pr="$2"
  local message="$3"

  echo "+ accept import review branch $branch"
  PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" - "$knowledge_repo" "$accepted_import_timestamp" "$review_pr" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import frontmatter

repo = Path(sys.argv[1])
timestamp = sys.argv[2]
review_pr = sys.argv[3]
changed: list[str] = []

for directory in ("principles", "decisions", "workflows", "projects"):
    entry_dir = repo / directory
    if not entry_dir.exists():
        continue
    for path in sorted(entry_dir.glob("*.md")):
        post = frontmatter.load(path)
        if post.metadata.get("status") != "proposed":
            continue
        post.metadata["status"] = "active"
        post.metadata["created_at"] = timestamp
        post.metadata["updated_at"] = timestamp
        review = post.metadata.get("review")
        if not isinstance(review, dict):
            review = {}
        review["required"] = True
        review["pr"] = review_pr
        post.metadata["review"] = review
        path.write_text(frontmatter.dumps(post))
        changed.append(path.relative_to(repo).as_posix())

if not changed:
    raise SystemExit("no proposed import entries found to accept")

print("Accepted imported entries:")
for item in changed:
    print(f"  - {item}")
PY
  run_in "$knowledge_repo" git add .
  run_in "$knowledge_repo" git \
    -c user.name="Jurati Dogfood" \
    -c user.email="jurati-dogfood@example.com" \
    commit -m "$message"
  run_in "$knowledge_repo" git checkout main
  run_in "$knowledge_repo" git merge --ff-only "$branch"
  run_in "$knowledge_repo" git push origin main
}

prepare_cache_repo() {
  local cache_root="$1"

  echo "+ prepare Jurati cache at $cache_root"
  PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" - "$remote_url" "$cache_root" <<'PY'
from __future__ import annotations

import sys

import git

from jurati.git.repo import ensure_repo

repo_path = ensure_repo(sys.argv[1], sys.argv[2])
repo = git.Repo(repo_path)
with repo.config_writer() as writer:
    writer.set_value("user", "name", "Jurati Dogfood")
    writer.set_value("user", "email", "jurati-dogfood@example.com")
print(repo_path)
PY
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
- curation cache dir: $curation_cache_dir
- isolated home: $home_dir
- goal used for context: $goal
- accepted import timestamp: $accepted_import_timestamp
- PR signal fixture: $pr_signal_fixture
- import output: $import_output
- curation output: $curation_output
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

mkdir -p \
  "$upstream_repo/$(dirname "$shared_contract_path")" \
  "$upstream_repo/src/auth" \
  "$upstream_repo/docs/adr"
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
cat > "$upstream_repo/docs/adr/0001-shared-auth-contract.md" <<'EOF'
# Shared auth contract is owned upstream

The auth API owns the shared session contract. The web app should not invent a
local token shape while an upstream auth-contract pull request is open.

Agents starting frontend auth work must check for labeled upstream contract
signals before changing the downstream session flow.
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

cat > "$pr_signal_fixture" <<EOF
{
  "signals": [
    {
      "provider": "github",
      "repo": "$upstream_name",
      "number": 7,
      "url": "https://github.com/$upstream_name/pull/7",
      "title": "Auth contract migration blocks frontend session rollout",
      "body_excerpt": "The session contract changes refreshWindowSeconds from 300 to 900 and adds rotationPolicy: server-driven. Downstream web work should wait or adapt to this open API PR.",
      "author": "alice",
      "state": "open",
      "labels": ["jurati"],
      "created_at": "$timestamp",
      "updated_at": "$timestamp",
      "changed_paths": ["$shared_contract_path"]
    },
    {
      "provider": "github",
      "repo": "$upstream_name",
      "number": 8,
      "url": "https://github.com/$upstream_name/pull/8",
      "title": "Merge auth contract refresh-window migration",
      "body_excerpt": "The auth contract migration has merged. Revalidate downstream session-flow knowledge before treating older contract guidance as current.",
      "author": "alice",
      "state": "merged",
      "labels": ["jurati", "auth", "contract"],
      "created_at": "$timestamp",
      "updated_at": "$timestamp",
      "merged_at": "$timestamp",
      "changed_paths": ["$shared_contract_path"]
    }
  ]
}
EOF

mkdir -p \
  "$downstream_repo/$(dirname "$shared_contract_path")" \
  "$downstream_repo/src/auth" \
  "$downstream_repo/docs/team-context"
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
cat > "$downstream_repo/docs/team-context/web-app-auth-session-work.md" <<'EOF'
# Web app auth session work

Workstream 4 validates that a downstream agent sees the upstream auth-contract
coordination signal early enough to avoid building against a stale session
contract.

The frontend session flow depends on `contracts/auth/session.json`; before
changing it, account for any labeled auth API contract pull requests.
EOF
cat > "$downstream_repo/docs/team-context/multi-repo-auth-coordination.md" <<'EOF'
# Multi-repo auth coordination workflow

Before frontend auth work starts, the agent should refresh Jurati context and
account for any jurati-labeled upstream auth PR before editing the downstream
session flow.

If the upstream contract is changing, pause or revise the downstream plan
instead of inventing a local token shape.
EOF
run_in "$downstream_repo" git init -b main 2>&1 | tee -a "$evidence"
commit_all "$downstream_repo" "feat: seed frontend auth session flow" 2>&1 | tee -a "$evidence"

append_evidence '```'

cat >> "$evidence" <<'EOF'

## Existing Docs Import Evidence

The dogfood gate imports existing project docs into the knowledge repo through
normal review branches, then simulates human review by accepting the imported
entries as active knowledge before the downstream agent starts.

```text
EOF

: > "$import_output"
run_in "$upstream_repo" "$JURATI_BIN" import-docs \
  --dry-run \
  --repo "$knowledge_repo" \
  --mode adr \
  --project auth-api \
  --project web-app \
  --tag auth \
  --tag contract \
  docs/adr 2>&1 | tee -a "$import_output" | tee -a "$evidence"
run_in "$upstream_repo" "$JURATI_BIN" import-docs \
  --repo "$knowledge_repo" \
  --branch "$auth_import_branch" \
  --mode adr \
  --project auth-api \
  --project web-app \
  --tag auth \
  --tag contract \
  docs/adr 2>&1 | tee -a "$import_output" | tee -a "$evidence"
accept_import_branch \
  "$auth_import_branch" \
  "https://github.com/$upstream_name/pull/11" \
  "chore(kb): accept imported auth contract context" 2>&1 \
  | tee -a "$import_output" | tee -a "$evidence"

run_in "$downstream_repo" "$JURATI_BIN" import-docs \
  --dry-run \
  --repo "$knowledge_repo" \
  --mode docs \
  --project web-app \
  --tag auth \
  --tag coordination \
  docs/team-context 2>&1 | tee -a "$import_output" | tee -a "$evidence"
run_in "$downstream_repo" "$JURATI_BIN" import-docs \
  --repo "$knowledge_repo" \
  --branch "$web_import_branch" \
  --mode docs \
  --project web-app \
  --tag auth \
  --tag coordination \
  docs/team-context 2>&1 | tee -a "$import_output" | tee -a "$evidence"
accept_import_branch \
  "$web_import_branch" \
  "https://github.com/$downstream_name/pull/12" \
  "chore(kb): accept imported web context" 2>&1 \
  | tee -a "$import_output" | tee -a "$evidence"

append_evidence '```'

grep -q 'Summary: 1 create, 0 skip, 0 reject' "$import_output"
grep -q 'Summary: 2 create, 0 skip, 0 reject' "$import_output"
grep -q 'Wrote import review branch:' "$import_output"
grep -q 'Accepted imported entries:' "$import_output"
grep -q 'decisions/shared-auth-contract-is-owned-upstream.md' "$import_output"
grep -q 'projects/web-app-auth-session-work.md' "$import_output"

cat >> "$evidence" <<'EOF'

## Startup And Handler Evidence

```text
EOF

run "$JURATI_BIN" validate "$knowledge_repo" 2>&1 | tee -a "$evidence"
run "$JURATI_BIN" install-claude-md --repo-path "$downstream_repo" --remote "$remote_url" \
  2>&1 | tee -a "$evidence"
run_in "$downstream_repo" env \
  JURATI_PR_SIGNAL_REPOS="$upstream_name" \
  JURATI_PR_SIGNAL_FIXTURE="$pr_signal_fixture" \
  "$JURATI_BIN" mcp-config --remote "$remote_url" --command "$JURATI_BIN" --write-project \
  2>&1 | tee -a "$evidence"
run_in "$downstream_repo" env \
  HOME="$home_dir" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  JURATI_PR_SIGNAL_REPOS="$upstream_name" \
  JURATI_PR_SIGNAL_FIXTURE="$pr_signal_fixture" \
  "$JURATI_BIN" doctor --check-startup 2>&1 | tee "$doctor_output" | tee -a "$evidence"
grep -q 'Ready for `jurati serve`: yes' "$doctor_output"
run_in "$downstream_repo" env \
  HOME="$home_dir" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$cache_dir" \
  JURATI_PR_SIGNAL_REPOS="$upstream_name" \
  JURATI_PR_SIGNAL_FIXTURE="$pr_signal_fixture" \
  "$JURATI_BIN" serve --check 2>&1 | tee -a "$evidence"

append_evidence '```'

cat >> "$evidence" <<'EOF'

## Curation Review Branch Evidence

The curation gate uses the same labeled signal fixture with a merged upstream
artifact. It must propose a normal review branch that marks related imported
durable knowledge for revalidation.

```text
EOF

: > "$curation_output"
prepare_cache_repo "$curation_cache_dir" 2>&1 | tee -a "$curation_output" | tee -a "$evidence"
run_in "$downstream_repo" env \
  PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  JURATI_KNOWLEDGE_REMOTE="$remote_url" \
  JURATI_CACHE_DIR="$curation_cache_dir" \
  JURATI_PR_SIGNAL_REPOS="$upstream_name" \
  JURATI_PR_SIGNAL_FIXTURE="$pr_signal_fixture" \
  JURATI_CURATION_WRITE=true \
  JURATI_CURATION_BRANCH="$curation_branch" \
  "$PYTHON_BIN" -m jurati.curation.run_hygiene 2>&1 \
  | tee -a "$curation_output" | tee -a "$evidence"

append_evidence '```'

grep -q 'Completed Artifact Revalidation' "$curation_output"
grep -q 'Wrote curation review branch:' "$curation_output"
grep -q "$curation_branch" "$curation_output"
grep -q 'marked for revalidation:' "$curation_output"
grep -q 'decisions/shared-auth-contract-is-owned-upstream.md' "$curation_output"

cat >> "$evidence" <<'EOF'

## Multi-Repo Tool Sequence

The scripted harness below uses the real Jurati MCP handler functions with
active refs disabled, plus simulated jurati-labeled upstream PR signals. It
checks goal-only startup context, curation advisories from the merged signal,
and a path-specific planning follow-up.

```jsonl
EOF

DOGFOOD_REMOTE_URL="$remote_url" \
DOGFOOD_CACHE_DIR="$cache_dir" \
DOGFOOD_UPSTREAM_REPO="$upstream_name" \
DOGFOOD_DOWNSTREAM_REPO="$downstream_name" \
DOGFOOD_CONTRACT_PATH="$shared_contract_path" \
DOGFOOD_GOAL="$goal" \
DOGFOOD_PR_SIGNAL_FIXTURE="$pr_signal_fixture" \
PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
"$PYTHON_BIN" - <<'PY' 2>&1 | tee "$tool_output" | tee -a "$evidence"
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import anyio
import git

from jurati.git.config import JuratiConfig, PRSignalsConfig
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.server import ServerState, SyncHealth, context, query, sync


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


def _event(tool: str, **payload: Any) -> None:
    print(json.dumps({"tool": tool, **payload}, sort_keys=True))


def _effects(payload: dict[str, Any]) -> list[str]:
    coordination = payload.get("coordination") or {}
    return [item["effect"] for item in coordination.get("guidance", [])]


def _recent_titles(payload: dict[str, Any]) -> list[str]:
    return [
        item["title"]
        for item in payload.get("recent", [])
        if isinstance(item, dict) and "title" in item
    ]


def _curation_titles(payload: dict[str, Any]) -> list[str]:
    curation = payload.get("curation") or {}
    return [
        item["entry_title"]
        for item in curation.get("completed_artifact_revalidation", [])
        if isinstance(item, dict) and "entry_title" in item
    ]


async def main() -> None:
    remote_url = os.environ["DOGFOOD_REMOTE_URL"]
    cache_dir = os.environ["DOGFOOD_CACHE_DIR"]
    upstream_repo = os.environ["DOGFOOD_UPSTREAM_REPO"]
    downstream_repo = os.environ["DOGFOOD_DOWNSTREAM_REPO"]
    contract_path = os.environ["DOGFOOD_CONTRACT_PATH"]
    goal = os.environ["DOGFOOD_GOAL"]
    pr_signal_fixture = os.environ["DOGFOOD_PR_SIGNAL_FIXTURE"]

    config = JuratiConfig(
        remote_url=remote_url,
        cache_dir=cache_dir,
        client_slug="multi-repo-dogfood",
        active_refs_enabled=False,
        pr_signals=PRSignalsConfig(repos=(upstream_repo,), fixture_path=pr_signal_fixture),
    )
    repo_path = ensure_repo(remote_url, cache_dir)
    repo = git.Repo(repo_path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Dogfood")
        writer.set_value("user", "email", "jurati-dogfood@example.com")
    fetch_all(repo_path, active_refs_enabled=False)
    now = datetime.now(UTC)

    state = ServerState(
        config=config,
        repo_path=repo_path,
        index=load_index_from_repo(repo_path, active_refs_enabled=False),
        last_sync=now,
        sync_health=SyncHealth(last_success=now),
    )
    ctx = _FakeCtx(state)

    sync_result = await sync(ctx=ctx)
    _event(
        "sync",
        status=sync_result["status"],
        entries=sync_result["entries"],
        active_refs_enabled=False,
        visibility=sync_result["visibility"],
    )

    goal_context = await context(ctx=ctx, repo=downstream_repo, goal=goal)
    goal_effects = _effects(goal_context)
    goal_recent_titles = _recent_titles(goal_context)
    goal_curation_titles = _curation_titles(goal_context)
    _event(
        "context_goal_only",
        repo=downstream_repo,
        goal=goal,
        effects=goal_effects,
        recent_titles=goal_recent_titles,
        summary=(goal_context.get("coordination") or {}).get("summary"),
    )
    _event(
        "context_curation",
        completed_titles=goal_curation_titles,
        summary=(goal_context.get("curation") or {}).get("summary"),
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
    if "Shared auth contract is owned upstream" not in goal_recent_titles:
        raise AssertionError("imported auth decision did not surface in startup context")
    if "Shared auth contract is owned upstream" not in goal_curation_titles:
        raise AssertionError("curation advisories did not include imported auth decision")
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

The scripted path showed that existing docs imported through review branches
seeded useful startup context, a merged upstream signal produced curation
advisories for imported durable knowledge, goal-only startup context surfaced
the upstream coordination signal, and a path-specific follow-up produced pause
guidance for $shared_contract_path. This validates the deterministic Jurati
behavior. A manual connected-agent run is still needed to confirm a real client
calls sync() and context() before local-only exploration in the downstream repo.
EOF

grep -q '"tool": "sync"' "$tool_output"
grep -q '"tool": "context_goal_only"' "$tool_output"
grep -q '"tool": "context_curation"' "$tool_output"
grep -q '"tool": "context_path_specific"' "$tool_output"
grep -q '"tool": "query"' "$tool_output"
grep -q '"tool": "developer_summary"' "$tool_output"
grep -q 'Shared auth contract is owned upstream' "$tool_output"
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
