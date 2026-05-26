#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-active-context-privacy-smoke.sh

Runs the focused active-context privacy gate for the dogfood roadmap. This is a
small release-gate smoke, not a full test suite.

It proves:
  - active refs are off unless repo policy opts in
  - active refs are not overlaid when disabled
  - repo policy enablement and TTL flow into project MCP config
  - active writes are TTL-bounded and content-policy gated
  - expired or restricted active context is absent from startup context

Environment:
  PYTHON_BIN      Python executable used for pytest. Defaults to python.
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
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$repo_root"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

tests=(
  "tests/test_server.py::TestContentPolicyWriteIntegration::test_active_record_requires_repo_policy_opt_in"
  "tests/git/test_repo.py::TestLoadIndex::test_active_refs_disabled_skips_overlay"
  "tests/git/test_repo.py::TestLoadIndex::test_overlays_active_refs"
  "tests/test_cli.py::TestAdoptionHelpers::test_mcp_config_write_project_carries_repo_active_refs_policy"
  "tests/test_cli.py::TestAdoptionHelpers::test_mcp_config_write_project_rejects_invalid_repo_ttl"
  "tests/test_server.py::TestContentPolicyWriteIntegration::test_active_record_defaults_expiry_from_policy_ttl"
  "tests/test_server.py::TestContentPolicyWriteIntegration::test_active_record_rejects_expiry_beyond_policy_ttl"
  "tests/test_server.py::TestContentPolicyWriteIntegration::test_active_record_rejects_review_required_content"
  "tests/test_server.py::TestContextPayload::test_context_excludes_expired_and_restricted_active_entries"
)

"$PYTHON_BIN" -m pytest -q "${tests[@]}"

grep -q "Active context remains" docs/adoption.md
grep -q "context is disabled by default" docs/security-privacy-content-safety-audit.md
grep -q "requires repo-owned policy" docs/security-privacy-content-safety-audit.md

echo "Jurati active-context privacy smoke passed."
