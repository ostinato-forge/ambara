#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-first-user-trial.sh [--keep] [--workdir PATH]

Creates disposable local repos and verifies the pre-agent Jurati first-user
setup path. This does not publish anything and does not touch global MCP config.

Options:
  --keep          Keep the generated trial directory.
  --workdir PATH  Use PATH as the trial directory instead of a fresh /tmp dir.

Environment:
  JURATI_BIN      Jurati executable to test. Defaults to .venv/bin/jurati when
                  present, otherwise jurati from PATH.
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

if [[ -z "${JURATI_BIN:-}" ]]; then
  if [[ -x "$repo_root/.venv/bin/jurati" ]]; then
    JURATI_BIN="$repo_root/.venv/bin/jurati"
  else
    JURATI_BIN="jurati"
  fi
fi

if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-first-user-trial.XXXXXX")"
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
project_repo="$workdir/example-project"
cache_dir="$workdir/cache"
home_dir="$workdir/home"
evidence="$workdir/evidence.md"
doctor_output="$workdir/doctor-output.txt"
remote_url="file://$knowledge_remote"

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

require_command git
require_command "$JURATI_BIN"

mkdir -p "$workdir"

cat > "$evidence" <<EOF
# Jurati First-User Trial Evidence

- trial directory: $workdir
- jurati command: $JURATI_BIN
- knowledge repo: $knowledge_repo
- knowledge remote: $remote_url
- project repo: $project_repo
- cache dir: $cache_dir
- isolated home: $home_dir

## Command Evidence

EOF

append_evidence '```text'
mkdir -p "$home_dir"

run git init --bare "$knowledge_remote" 2>&1 | tee -a "$evidence"

mkdir -p "$project_repo"
run_in "$project_repo" git init -b main 2>&1 | tee -a "$evidence"
printf '# Example Project\n' > "$project_repo/README.md"
run_in "$project_repo" git add README.md 2>&1 | tee -a "$evidence"
run_in "$project_repo" git \
  -c user.name="Jurati Trial" \
  -c user.email="jurati-trial@example.com" \
  commit -m "docs: initialize example project" 2>&1 | tee -a "$evidence"

run_in "$project_repo" "$JURATI_BIN" onboard \
  --yes \
  --remote "$remote_url" \
  --knowledge-repo "$knowledge_repo" \
  --project-repo "$project_repo" \
  --pack engineering \
  2>&1 | tee -a "$evidence"

run_in "$knowledge_repo" git init -b main 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git add . 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git \
  -c user.name="Jurati Trial" \
  -c user.email="jurati-trial@example.com" \
  commit -m "docs: initialize jurati knowledge repo" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git remote add origin "$remote_url" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git push -u origin main 2>&1 | tee -a "$evidence"

run "$JURATI_BIN" validate "$knowledge_repo" 2>&1 | tee -a "$evidence"
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

grep -q 'sync()' "$project_repo/CLAUDE.md"
grep -q 'context()' "$project_repo/CLAUDE.md"
grep -q 'hard precondition' "$project_repo/CLAUDE.md"
grep -q 'local-only context' "$project_repo/CLAUDE.md"
grep -q 'mcp__jurati__context' "$project_repo/.claude/settings.json"
grep -q 'jurati-' "$project_repo/.mcp.json"

append_evidence '```'

cat >> "$evidence" <<'EOF'

## Generated Files To Inspect

- `example-project/CLAUDE.md`
- `example-project/.claude/settings.json`
- `example-project/.mcp.json`
- `jurati-knowledge/.jurati/config.yaml`
- `jurati-knowledge/projects/first-shared-context.md`
- `jurati-knowledge/workflows/daily-shared-context-loop.md`

## Manual Agent Trial

Open a fresh agent session in `example-project` with the generated MCP config
enabled.

### Prompt Battery

Prompt 1:

```text
Before editing anything, tell me what context matters for adding a health-check
endpoint to this project.
```

Expected first behavior:

- The first meaningful agent action is `sync()`.
- The next meaningful agent action is `context(repo=..., goal=...)`.
- The agent summarizes relevant team context in plain language before local
  file exploration.
- The agent does not expose entry IDs, ref paths, branch plumbing, or knowledge
  repo lifecycle instructions.

Prompt 2:

```text
Before you inspect git or read files, should this project add the endpoint in
the app router or deployment config?
```

Expected behavior:

- The agent still treats `sync()` then `context()` as a hard precondition.
- The agent must not inspect git state before startup context is loaded.
- Local-only context is not treated as an acceptable substitute.

Prompt 3:

```text
Save this handoff for the next agent: health-check work is exploratory, and the
main question is whether it belongs in the app router or deployment config.
```

Expected behavior:

- The agent maps the normal request to the appropriate write path.
- The developer-facing confirmation is one work-focused sentence.
- The response does not ask the person to manage the knowledge repo.

## Result

Jurati first-user trial setup passed.
EOF

echo ""
echo "Jurati first-user trial setup passed."
echo "Evidence: $evidence"
if [[ "$keep" == true ]]; then
  echo "Trial directory kept: $workdir"
else
  echo "Trial directory will be removed. Re-run with --keep to inspect generated files."
fi
