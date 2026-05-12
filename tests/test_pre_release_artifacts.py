from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pre_release_build_plan_tracks_quality_plan_and_issue() -> None:
    plan = (ROOT / "docs" / "pre-release-build-plan.md").read_text(encoding="utf-8")

    assert "https://github.com/ostinato-forge/jurati/issues/43" in plan
    assert "Reproducible First-User Trial" in plan
    assert "Installed-Package Smoke" in plan
    assert "Multi-Repo Coordination Dogfood" in plan
    assert "scripted harness passed" in plan


def test_adversarial_hardening_matrix_tracks_quality_plan_scenarios() -> None:
    doc = (ROOT / "docs" / "pre-release-adversarial-hardening.md").read_text(encoding="utf-8")
    scenarios = [
        "Duplicate global and project MCP config",
        "Missing `JURATI_KNOWLEDGE_REMOTE`",
        "Unavailable GitHub auth",
        "Stale active context",
        "Conflicting decisions",
        "Restricted entry linked by public entry",
        "Bad context pack tarball layout",
        "Context pack with secrets",
        "Labeled PR with unavailable changed paths",
        "Unlabeled relevant PR",
        "Agent asks user to run raw MCP JSON",
        "Agent exposes entry IDs or ref paths",
        "Agent skips startup context",
    ]

    assert "scripts/pre-release-adversarial-smoke.sh" in doc
    assert "manual gate outside the Codex sandbox" in doc
    for scenario in scenarios:
        assert scenario in doc


def test_release_readiness_review_records_current_decision_and_evidence() -> None:
    doc = (ROOT / "docs" / "pre-release-readiness-review.md").read_text(encoding="utf-8")

    assert "Jurati is not ready for a first external user yet." in doc
    assert "575 passed, 1 skipped" in doc
    assert "scripts/pre-release-installed-package-smoke.sh --keep" in doc
    assert "scripts/pre-release-single-repo-dogfood.sh --keep" in doc
    assert "scripts/pre-release-multi-repo-dogfood.sh --keep" in doc
    assert "scripts/pre-release-adversarial-smoke.sh" in doc
    assert "#43 Pre-release quality plan" in doc
    assert "#19 Roadmap: make Jurati ambient in daily agent work" in doc


def test_adversarial_smoke_script_runs_named_validation_owners() -> None:
    script = (ROOT / "scripts" / "pre-release-adversarial-smoke.sh").read_text(encoding="utf-8")

    assert "test_doctor_detects_global_project_server_name_collision" in script
    assert "test_serve_check_missing_remote_fails" in script
    assert "test_no_token_skips_api_candidate" in script
    assert "test_query_excludes_expired_by_default" in script
    assert "test_generate_static_html_hides_restricted_link_targets" in script
    assert "test_plan_context_import_rejects_secret_content" in script
    assert "test_missing_paths_status_surfaces_clarify_guidance" in script
    assert "test_creates_claude_md" in script


def test_client_docs_prevent_raw_mcp_and_over_disclosure() -> None:
    clients = (ROOT / "docs" / "clients.md").read_text(encoding="utf-8")
    claude = (ROOT / "docs" / "claude-md-template.md").read_text(encoding="utf-8")

    assert "Do not fall back to raw MCP protocol messages" in clients
    assert "hash-specific" in clients
    assert "Before reading files" in claude
    assert "Never expose Jurati internals" in claude
    assert "entry IDs, branch names, ref paths, PR numbers" in claude
    assert "mcp__jurati-a1b2c3d4__sync" in claude


def test_first_user_trial_script_documents_expected_agent_behavior() -> None:
    script = (ROOT / "scripts" / "pre-release-first-user-trial.sh").read_text(encoding="utf-8")

    assert "quickstart" in script
    assert "install-claude-md" in script
    assert "mcp-config --remote" in script
    assert "doctor --check-startup" in script
    assert "Ready for `jurati serve`: yes" in script
    assert 'HOME="$home_dir"' in script
    assert "serve --check" in script
    assert "Jurati first-user trial setup passed." in script
    assert "sync()" in script
    assert "context(repo=..., goal=...)" in script


def test_installed_package_smoke_runs_first_user_trial_with_installed_cli() -> None:
    script = (ROOT / "scripts" / "pre-release-installed-package-smoke.sh").read_text(
        encoding="utf-8"
    )

    assert "pip wheel" in script
    assert "--no-index" in script
    assert "--find-links" in script
    assert "pre-release-first-user-trial.sh" in script
    assert 'env JURATI_BIN="$installed_jurati"' in script
    assert "Jurati first-user trial setup passed." in script
    assert "Ready for `jurati serve`: yes" in script


def test_single_repo_dogfood_harness_documents_first_agent_order() -> None:
    script = (ROOT / "scripts" / "pre-release-single-repo-dogfood.sh").read_text(encoding="utf-8")

    assert "install-claude-md" in script
    assert "doctor --check-startup" in script
    assert "serve --check" in script
    assert 'tool": "sync' in script
    assert 'tool": "context' in script
    assert 'tool": "query' in script
    assert "developer_summary" in script
    assert "Pre-release confidence before features" in script


def test_multi_repo_dogfood_harness_documents_coordination_signal() -> None:
    script = (ROOT / "scripts" / "pre-release-multi-repo-dogfood.sh").read_text(encoding="utf-8")

    assert "ostinato-dogfood/auth-api" in script
    assert "ostinato-dogfood/web-app" in script
    assert "PRSignal" in script
    assert "SignalCache" in script
    assert "context_goal_only" in script
    assert "context_path_specific" in script
    assert "pause" in script
    assert "developer_summary" in script


def test_single_repo_dogfood_run_records_connected_agent_gate() -> None:
    doc = (ROOT / "docs" / "pre-release-dogfood-runs.md").read_text(encoding="utf-8")

    assert "https://github.com/ostinato-forge/jurati/issues/43" in doc
    assert "scripted harness passed" in doc
    assert "manual connected-agent startup gate passed" in doc
    assert "`install-claude-md` treated" in doc
    assert 'any `CLAUDE.md` that mentioned "Jurati" as already installed' in doc
    assert "hash-specific" in doc
    assert "no permission denials" in doc
    assert "called `sync()` then `context()` before reading files" in doc


def test_multi_repo_dogfood_run_records_coordination_evidence() -> None:
    doc = (ROOT / "docs" / "pre-release-dogfood-runs.md").read_text(encoding="utf-8")

    assert "Multi-Repo Coordination Dogfood Harness" in doc
    assert "ostinato-dogfood/auth-api" in doc
    assert "ostinato-dogfood/web-app" in doc
    assert "Goal-only startup context returned a coordination effect: `revise`" in doc
    assert "Path-specific context returned a coordination effect: `pause`" in doc
    assert "Alice's upstream auth contract PR should be accounted for" in doc
    assert "fixture-backed PR-signal source" in doc
