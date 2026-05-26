#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/obsidian-import-user-smoke.sh

Runs a user-style import smoke against docs/examples/shareable-note-export.
The fixture is synthetic but shaped like a shareable vault export: repo notes,
tool notes, error notes, learning notes, an old export manifest, templates,
attachments, a Canvas file, a private note, and an unsupported embed.

Environment:
  JURATI_BIN   Jurati executable. Defaults to .venv/bin/jurati, then jurati.
  KEEP         Set to 1 to keep the temporary smoke directory.
USAGE
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -gt 0 ]]; then
  echo "error: unknown argument: $1" >&2
  usage >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$repo_root/docs/examples/shareable-note-export"

if [[ -n "${JURATI_BIN:-}" ]]; then
  jurati_bin="$JURATI_BIN"
elif [[ -x "$repo_root/.venv/bin/jurati" ]]; then
  jurati_bin="$repo_root/.venv/bin/jurati"
else
  jurati_bin="jurati"
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-obsidian-import-smoke.XXXXXX")"
if [[ "${KEEP:-0}" != "1" ]]; then
  trap 'rm -rf "$tmp_dir"' EXIT
fi

kb="$tmp_dir/knowledge"

run() {
  echo
  echo "\$ $*"
  "$@"
}

capture_expected_failure() {
  local output_file="$1"
  shift
  echo
  echo "\$ $*"
  set +e
  "$@" >"$output_file" 2>&1
  local status=$?
  set -e
  cat "$output_file"
  if [[ "$status" -ne 1 ]]; then
    echo "expected command to exit 1, got $status" >&2
    exit 1
  fi
}

assert_contains() {
  local needle="$1"
  local file="$2"
  if ! grep -Fq "$needle" "$file"; then
    echo "missing expected output: $needle" >&2
    exit 1
  fi
}

run git init "$kb"
run git -C "$kb" config user.name "Jurati Import Smoke"
run git -C "$kb" config user.email "jurati-import-smoke@example.com"
run "$jurati_bin" init --no-examples "$kb"
run git -C "$kb" add .
run git -C "$kb" commit -m "initial knowledge repo"

messy_output="$tmp_dir/messy-dry-run.txt"
capture_expected_failure \
  "$messy_output" \
  "$jurati_bin" import-docs \
  --dry-run \
  --mode obsidian \
  --repo "$kb" \
  --project example-platform \
  "$fixture"

assert_contains "Summary: 6 create, 5 skip, 2 reject" "$messy_output"
assert_contains "shareable-note-export/Tools/deploy-cli.md -> workflows/deploy-cli.md" "$messy_output"
assert_contains "shareable-note-export/Errors/ci-cache-loop.md -> workflows/ci-cache-loop.md" "$messy_output"
assert_contains "shareable-note-export/Repos/reporting.service.md -> projects/reporting-service.md" "$messy_output"
assert_contains "Private Notes/local-handoff.md: personal or local-only source" "$messy_output"
assert_contains "Repos/embed-example.md: Obsidian embeds are unsupported" "$messy_output"

clean_sources=(
  "$fixture/Repos/api-service.md"
  "$fixture/Repos/reporting.service.md"
  "$fixture/Tools/deploy-cli.md"
  "$fixture/Errors/ci-cache-loop.md"
  "$fixture/Learnings/platform-architecture.md"
  "$fixture/Decisions/server-driven-tokens.md"
)

clean_output="$tmp_dir/clean-dry-run.txt"
run "$jurati_bin" import-docs \
  --dry-run \
  --mode obsidian \
  --repo "$kb" \
  --project example-platform \
  "${clean_sources[@]}" | tee "$clean_output"
assert_contains "Summary: 6 create, 0 skip, 0 reject" "$clean_output"

run "$jurati_bin" import-docs \
  --mode obsidian \
  --repo "$kb" \
  --branch jurati/import-obsidian-user-smoke \
  --project example-platform \
  "${clean_sources[@]}"

run git -C "$kb" branch --show-current
run git -C "$kb" log --oneline -2
run sed -n '1,120p' "$kb/workflows/deploy-cli.md"
run "$jurati_bin" validate "$kb"

echo
echo "Jurati Obsidian import user smoke passed."
if [[ "${KEEP:-0}" == "1" ]]; then
  echo "Smoke directory kept at: $tmp_dir"
fi
