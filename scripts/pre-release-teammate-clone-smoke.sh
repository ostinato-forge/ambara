#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-teammate-clone-smoke.sh [--keep] [--workdir PATH]

Creates a participating project repo, commits its repo-owned Jurati setup, then
verifies a fresh teammate clone can run one documented command and get a
working read-only connection without personal remote env or teammate tracking.

Options:
  --keep          Keep the generated smoke directory.
  --workdir PATH  Use PATH as the smoke directory instead of a fresh /tmp dir.

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
if [[ "$JURATI_BIN" != /* ]]; then
  if [[ "$JURATI_BIN" == */* ]]; then
    JURATI_BIN="$(cd "$(dirname "$JURATI_BIN")" && pwd)/$(basename "$JURATI_BIN")"
  else
    JURATI_BIN="$(command -v "$JURATI_BIN")"
  fi
fi

if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-teammate-clone.XXXXXX")"
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
maintainer_repo="$workdir/maintainer-project"
project_remote="$workdir/maintainer-project.git"
teammate_clone="$workdir/teammate-clone"
teammate_home="$workdir/teammate-home"
cache_dir="$workdir/teammate-cache"
evidence="$workdir/evidence.md"
doctor_output="$workdir/doctor-output.txt"
serve_output="$workdir/serve-output.txt"
remote_url="file://$knowledge_remote"
project_remote_url="file://$project_remote"

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

cat > "$evidence" <<EOF
# Jurati Fresh-Clone Teammate Smoke Evidence

- smoke directory: $workdir
- jurati command: $JURATI_BIN
- knowledge repo: $knowledge_repo
- knowledge remote: $remote_url
- maintainer project repo: $maintainer_repo
- project remote: $project_remote_url
- teammate clone: $teammate_clone
- isolated teammate home: $teammate_home
- teammate cache dir: $cache_dir

## Command Evidence

EOF

append_evidence '```text'

run git init --bare --initial-branch=main "$knowledge_remote" 2>&1 | tee -a "$evidence"
run git init --bare --initial-branch=main "$project_remote" 2>&1 | tee -a "$evidence"

mkdir -p "$maintainer_repo"
run_in "$maintainer_repo" git init -b main 2>&1 | tee -a "$evidence"
printf '# Participating Project\n' > "$maintainer_repo/README.md"
run_in "$maintainer_repo" git add README.md 2>&1 | tee -a "$evidence"
run_in "$maintainer_repo" git \
  -c user.name="Jurati Maintainer" \
  -c user.email="jurati-maintainer@example.com" \
  commit -m "docs: initialize participating project" 2>&1 | tee -a "$evidence"

run_in "$maintainer_repo" "$JURATI_BIN" onboard \
  --yes \
  --remote "$remote_url" \
  --knowledge-repo "$knowledge_repo" \
  --project-repo "$maintainer_repo" \
  --command "$JURATI_BIN" \
  --pack engineering \
  2>&1 | tee -a "$evidence"

run_in "$knowledge_repo" git init -b main 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git add . 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git \
  -c user.name="Jurati Maintainer" \
  -c user.email="jurati-maintainer@example.com" \
  commit -m "docs: initialize jurati knowledge repo" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git remote add origin "$remote_url" 2>&1 | tee -a "$evidence"
run_in "$knowledge_repo" git push -u origin main 2>&1 | tee -a "$evidence"

run "$JURATI_BIN" validate "$knowledge_repo" 2>&1 | tee -a "$evidence"

run_in "$maintainer_repo" git add \
  README.md \
  CLAUDE.md \
  .claude/settings.json \
  .jurati/config.yaml \
  .mcp.json \
  2>&1 | tee -a "$evidence"
run_in "$maintainer_repo" git \
  -c user.name="Jurati Maintainer" \
  -c user.email="jurati-maintainer@example.com" \
  commit -m "chore: add jurati team setup" 2>&1 | tee -a "$evidence"
run_in "$maintainer_repo" git remote add origin "$project_remote_url" 2>&1 | tee -a "$evidence"
run_in "$maintainer_repo" git push -u origin main 2>&1 | tee -a "$evidence"

run git clone --quiet "$project_remote_url" "$teammate_clone" 2>&1 | tee -a "$evidence"
mkdir -p "$teammate_home"

append_evidence ""
append_evidence "# One documented command from fresh clone"
run_in "$teammate_clone" env \
  HOME="$teammate_home" \
  JURATI_KNOWLEDGE_REMOTE="" \
  JURATI_CACHE_DIR="$cache_dir" \
  "$JURATI_BIN" doctor --team --check-startup --strict \
  2>&1 | tee "$doctor_output" | tee -a "$evidence"

append_evidence ""
append_evidence "# Read-only server preflight from fresh clone"
run_in "$teammate_clone" env \
  HOME="$teammate_home" \
  JURATI_KNOWLEDGE_REMOTE="" \
  JURATI_CACHE_DIR="$cache_dir" \
  "$JURATI_BIN" serve --check \
  2>&1 | tee "$serve_output" | tee -a "$evidence"

append_evidence '```'

grep -q 'JURATI_KNOWLEDGE_REMOTE: file://' "$doctor_output"
grep -q 'repo participation marker: yes' "$doctor_output"
grep -q 'project MCP config:        yes' "$doctor_output"
grep -q 'startup contract:          yes' "$doctor_output"
grep -q 'read-only tools:           yes' "$doctor_output"
grep -q 'privacy boundary:          repo readiness only; no teammate install/presence tracking' "$doctor_output"
grep -q 'Team ready:                yes' "$doctor_output"
grep -q 'Ready for `jurati serve`: yes' "$doctor_output"
grep -q 'Jurati serve preflight' "$serve_output"
grep -q 'knowledge remote: file://' "$serve_output"
grep -q "$JURATI_BIN" "$teammate_clone/.mcp.json"

if grep -Eiq 'tools/call|mcpServers|teammate .*installed|presence: yes|participation: yes' "$doctor_output"; then
  echo "error: doctor output exposed raw MCP protocol or teammate tracking language" >&2
  exit 1
fi

cat >> "$evidence" <<EOF

## Generated Files To Inspect

- \`maintainer-project/.jurati/config.yaml\`
- \`maintainer-project/CLAUDE.md\`
- \`maintainer-project/.claude/settings.json\`
- \`maintainer-project/.mcp.json\`
- \`teammate-clone/.jurati/config.yaml\`
- \`teammate-clone/CLAUDE.md\`
- \`teammate-clone/.claude/settings.json\`
- \`teammate-clone/.mcp.json\`

## Result

Fresh-clone teammate smoke passed.

The teammate clone needed one documented Jurati command:

\`\`\`text
jurati doctor --team --check-startup --strict
\`\`\`

The command discovered the repo-owned remote from \`.jurati/config.yaml\`,
verified project MCP config and startup instructions, fetched/indexed the
knowledge repo, and reported repo readiness without personal remote env,
teammate install status, presence, reads, or participation.
EOF

echo ""
echo "Jurati fresh-clone teammate smoke passed."
echo "Evidence: $evidence"
if [[ "$keep" == true ]]; then
  echo "Smoke directory kept: $workdir"
else
  echo "Smoke directory will be removed. Re-run with --keep to inspect generated files."
fi
