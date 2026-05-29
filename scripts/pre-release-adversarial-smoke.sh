#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/pre-release-adversarial-smoke.sh

Runs the high-signal adversarial tests used by the pre-release hardening matrix.
This is intentionally narrower than the full test suite; it is a quick check
for the failure modes most likely to break first external use.

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
  "tests/test_cli.py::TestMcpConfigCollision::test_doctor_detects_global_project_server_name_collision"
  "tests/test_cli.py::TestMcpConfigCollision::test_doctor_does_not_block_on_unrelated_server_name_collision"
  "tests/test_cli.py::TestAdoptionHelpers::test_doctor_without_remote_explains_fast_path"
  "tests/test_cli.py::TestAdoptionHelpers::test_doctor_strict_without_remote_fails"
  "tests/test_cli.py::TestAdoptionHelpers::test_serve_check_missing_remote_fails"
  "tests/test_cli.py::TestAdoptionHelpers::test_doctor_check_startup_explains_unusable_cache_dir"
  "tests/git/test_pr.py::TestCreatePrCandidateIteration::test_no_token_skips_api_candidate"
  "tests/git/test_pr.py::TestCreatePrGhCliStrategy::test_gh_cli_failure_falls_to_branch_only"
  "tests/test_server.py::TestQueryTool::test_query_excludes_expired_by_default"
  "tests/test_server.py::TestContextPayload::test_context_excludes_expired_and_restricted_active_entries"
  "tests/core/test_curation.py::TestDetectContradictions::test_overlapping_titles_flagged"
  "tests/test_server.py::TestReadTool::test_read_backlinks_do_not_leak_restricted_sources"
  "tests/core/test_static_html.py::test_generate_static_html_hides_restricted_link_targets"
  "tests/read_model/test_sqlite.py::test_query_read_model_filters_restricted_and_expired_entries"
  "tests/core/test_import_context.py::test_plan_context_import_requires_manifest"
  "tests/core/test_import_context.py::test_plan_context_import_rejects_secret_content"
  "tests/core/test_import_context.py::test_plan_context_import_rejects_content_policy_review_content"
  "tests/test_server_coordination.py::TestBuildCoordination::test_missing_paths_status_surfaces_clarify_guidance"
  "tests/providers/test_github_prs.py::TestFetchLabeledPRs::test_successful_fetch"
  "tests/test_privacy_coordination.py::TestOnlyLabeledPRs::test_unconfigured_repos_not_queried"
  "tests/test_server.py::TestContentPolicyWriteIntegration::test_active_record_requires_repo_policy_opt_in"
  "tests/test_server.py::TestContentPolicyWriteIntegration::test_active_record_rejects_expiry_beyond_policy_ttl"
  "tests/test_server.py::TestReceipts::test_active_write_receipt_biases_to_human_confirmation"
  "tests/test_server.py::TestReceipts::test_pr_write_receipt_biases_to_human_confirmation"
  "tests/test_cli.py::TestInstallClaudeMd::test_creates_claude_md"
)

"$PYTHON_BIN" -m pytest -q "${tests[@]}"

grep -q "Do not fall back to raw MCP protocol messages" docs/clients.md
grep -q "Before reading files" docs/claude-md-template.md
grep -q "Never expose Jurati internals" docs/claude-md-template.md

echo "Jurati adversarial smoke passed."
