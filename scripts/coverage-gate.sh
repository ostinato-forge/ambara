#!/usr/bin/env bash
set -euo pipefail

# Coverage gate: run the suite once under coverage, enforce the whole-tree
# floor (85%, configured in pyproject [tool.coverage.report]) and the
# per-package floors below.
#
# Per-package floors are a one-way ratchet. core/ is the pure, invariant-bearing
# domain; CLAUDE.md targets 95%+ there, so it is the one package locked above
# the global floor. Other packages stay at the global floor while they are
# still under active structural work; ratchet them here once they stabilise.
PACKAGE_FLOORS=(
  "core 95"
)

cd "$(dirname "$0")/.."

python="${PYTHON:-.venv/bin/python}"

# Run hermetically. The suite initialises throwaway git repos; an ambient global
# pre-commit hook or init template (init.templateDir / core.hooksPath) would be
# copied into them and break unrelated git tests. Pin a minimal git env so the
# gate is reproducible regardless of the developer's global git config.
gate_gitconfig="$(mktemp)"
trap 'rm -f "$gate_gitconfig"' EXIT
cat > "$gate_gitconfig" <<'CFG'
[user]
  name = Coverage Gate
  email = gate@ambara.invalid
[init]
  defaultBranch = main
[commit]
  gpgsign = false
[pack]
  threads = 1
CFG
export GIT_CONFIG_GLOBAL="$gate_gitconfig"
export GIT_CONFIG_SYSTEM=/dev/null

# Single instrumented run. The global floor is enforced here via the coverage
# config; -o addopts="" drops the default -v/--strict-markers noise.
"$python" -m pytest -q -p no:cacheprovider -o addopts="" \
  --cov=ambara --cov-report=term-missing:skip-covered

echo
echo "Per-package coverage floors:"
status=0
for entry in "${PACKAGE_FLOORS[@]}"; do
  pkg="${entry%% *}"
  floor="${entry##* }"
  if "$python" -m coverage report --include="*/ambara/${pkg}/*" \
    --fail-under="$floor" >/dev/null 2>&1; then
    actual="$("$python" -m coverage report --include="*/ambara/${pkg}/*" \
      2>/dev/null | awk '/^TOTAL/ {print $NF}')"
    echo "  ok    ${pkg} ${actual} >= ${floor}%"
  else
    actual="$("$python" -m coverage report --include="*/ambara/${pkg}/*" \
      2>/dev/null | awk '/^TOTAL/ {print $NF}')"
    echo "  FAIL  ${pkg} ${actual} < ${floor}%" >&2
    status=1
  fi
done

echo
echo "Performance baseline:"
if ! "$python" scripts/perf-baseline.py --check; then
  status=1
fi

if [[ "$status" -ne 0 ]]; then
  echo "coverage gate: one or more checks failed" >&2
fi
exit "$status"
