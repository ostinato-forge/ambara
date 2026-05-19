# Pre-Release Adversarial Hardening

Tracking issue: https://github.com/ostinato-forge/jurati/issues/43

## Purpose

This document turns the adversarial scenarios in the pre-release quality plan
into named validation owners. The goal is to keep release confidence grounded in
repeatable checks, not in a vague feeling that the happy path worked.

Run the high-signal automated set with:

```bash
scripts/pre-release-adversarial-smoke.sh
```

The full static gate is still:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src
git diff --check
```

## Validation Matrix

| Scenario | Validation owner | Evidence |
|----------|------------------|----------|
| Duplicate Jurati global and project MCP config | Automated test | `tests/test_cli.py::TestMcpConfigCollision::test_doctor_detects_global_project_server_name_collision` |
| Duplicate non-Jurati MCP config | Automated test | `tests/test_cli.py::TestMcpConfigCollision::test_doctor_does_not_block_on_unrelated_server_name_collision` |
| Missing `JURATI_KNOWLEDGE_REMOTE` | Automated tests | `tests/test_cli.py::TestAdoptionHelpers::test_doctor_without_remote_explains_fast_path`, `test_doctor_strict_without_remote_fails`, and `test_serve_check_missing_remote_fails` |
| Unwritable `JURATI_CACHE_DIR` | Automated test | `tests/test_cli.py::TestAdoptionHelpers::test_doctor_check_startup_explains_unusable_cache_dir` |
| Unavailable GitHub auth | Automated tests | `tests/git/test_pr.py::TestCreatePrCandidateIteration::test_no_token_skips_api_candidate`, `tests/git/test_pr.py::TestCreatePrGhCliStrategy::test_gh_cli_failure_falls_to_branch_only`, and provider error-path tests |
| Stale active context | Automated tests | `tests/test_server.py::TestQueryTool::test_query_excludes_expired_by_default` and hygiene/status tests |
| Conflicting decisions | Automated test | `tests/core/test_curation.py::TestDetectContradictions::test_overlapping_titles_flagged` |
| Restricted entry linked by public entry | Automated tests | `tests/test_server.py::TestReadTool::test_read_backlinks_do_not_leak_restricted_sources`, `tests/core/test_static_html.py::test_generate_static_html_hides_restricted_link_targets`, and read-model restricted filtering |
| Bad context pack tarball layout | Automated tests | `tests/core/test_import_context.py::test_plan_context_import_requires_manifest` and source-frontmatter rejection tests |
| Context pack with secrets | Automated test | `tests/core/test_import_context.py::test_plan_context_import_rejects_secret_content` |
| Labeled PR with unavailable changed paths | Automated test | `tests/test_server_coordination.py::TestBuildCoordination::test_missing_paths_status_surfaces_clarify_guidance` |
| Unlabeled relevant PR | Automated tests | `tests/providers/test_github_prs.py::TestFetchLabeledPRs::test_successful_fetch` proves the provider query is label-scoped; privacy tests prove unconfigured repos are not queried |
| Agent asks user to run raw MCP JSON | Documentation and CLI tests | `docs/clients.md` explicitly forbids raw MCP protocol fallback; duplicate-config CLI output avoids `tools/call` instructions |
| Agent exposes entry IDs or ref paths | Automated tests and client docs | receipt tests in `tests/test_server.py::TestReceipts`, `tests/test_cli.py::TestInstallClaudeMd::test_creates_claude_md`, and `docs/claude-md-template.md` |
| Agent skips startup context | Scripted dogfood plus manual gate | single-repo and multi-repo dogfood harnesses prove the intended tool order; real connected-agent compliance remains a manual gate outside the Codex sandbox or from a clean disposable branch |

## Manual Gates

The connected-agent checks stay manual for now because running an external
agent with normal auth/network access from this dirty local workspace crosses
the project privacy boundary. Run them from a clean disposable branch or outside
the Codex sandbox.

Manual checks:

- In a generated single-repo dogfood clone, confirm the first meaningful agent
  actions are `sync()` and `context()` before local repo exploration.
- In a generated multi-repo dogfood downstream repo, confirm the agent states
  the upstream PR coordination plainly before editing the shared target.
- Confirm developer-facing responses do not expose entry IDs, branch names, ref
  paths, raw MCP protocol messages, expiry mechanics, or knowledge repo chores.

Any failure becomes a focused issue or patch before the release-readiness
review.
