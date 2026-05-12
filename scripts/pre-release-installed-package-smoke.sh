#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-installed-package-smoke.sh [--keep] [--workdir PATH]

Builds a Jurati wheelhouse, installs Jurati into a clean virtual environment,
and runs the first-user trial using the installed jurati command.

Options:
  --keep          Keep the generated smoke directory.
  --workdir PATH  Use PATH as the smoke directory instead of a fresh /tmp dir.

Environment:
  PYTHON_BIN      Python executable used to build and create the venv.
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

if [[ -z "$workdir" ]]; then
  workdir="$(mktemp -d "${TMPDIR:-/tmp}/jurati-installed-smoke.XXXXXX")"
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

wheelhouse="$workdir/wheelhouse"
venv="$workdir/venv"
trial_dir="$workdir/first-user-trial"
evidence="$workdir/evidence.md"
installed_jurati="$venv/bin/jurati"

run() {
  echo "+ $*"
  "$@"
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

require_command "$PYTHON_BIN"
require_command git

mkdir -p "$wheelhouse"

cat > "$evidence" <<EOF
# Jurati Installed-Package Smoke Evidence

- smoke directory: $workdir
- python command: $PYTHON_BIN
- wheelhouse: $wheelhouse
- virtualenv: $venv
- installed jurati: $installed_jurati
- first-user trial directory: $trial_dir

## Command Evidence

EOF

append_evidence '```text'

run "$PYTHON_BIN" -m pip wheel "$repo_root" --wheel-dir "$wheelhouse" \
  2>&1 | tee -a "$evidence"
run "$PYTHON_BIN" -m venv "$venv" 2>&1 | tee -a "$evidence"
run "$venv/bin/python" -m pip install --no-index --find-links "$wheelhouse" jurati \
  2>&1 | tee -a "$evidence"
run "$installed_jurati" --help 2>&1 | tee -a "$evidence"

run env JURATI_BIN="$installed_jurati" \
  "$repo_root/scripts/pre-release-first-user-trial.sh" --keep --workdir "$trial_dir" \
  2>&1 | tee -a "$evidence"

grep -q 'Jurati first-user trial setup passed.' "$trial_dir/evidence.md"
grep -q 'Ready for `jurati serve`: yes' "$trial_dir/doctor-output.txt"
grep -q "$installed_jurati" "$trial_dir/evidence.md"

append_evidence '```'

cat >> "$evidence" <<EOF

## Result

Installed-package smoke passed.

The first-user trial was run with the installed command:

\`\`\`text
$installed_jurati
\`\`\`

First-user evidence:

\`\`\`text
$trial_dir/evidence.md
\`\`\`
EOF

echo ""
echo "Jurati installed-package smoke passed."
echo "Evidence: $evidence"
if [[ "$keep" == true ]]; then
  echo "Smoke directory kept: $workdir"
else
  echo "Smoke directory will be removed. Re-run with --keep to inspect generated files."
fi
