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


def test_forward_build_plan_tracks_next_execution_order() -> None:
    plan = (ROOT / "docs" / "build-plan.md").read_text(encoding="utf-8")

    assert "### Phase 0: Package Trust And Correctness" in plan
    assert "### Phase 0.5: Server Shape Cleanup" in plan
    assert "### Phase 1: Repo-Discovered Team Adoption" in plan
    assert "### Phase 2: Existing Knowledge Bootstrap" in plan
    assert "https://github.com/ostinato-forge/jurati/issues/104" in plan
    assert f"{'Obs'}idian vaults" in plan
    assert "curated, reviewed subset agents must" in plan
    assert "### Dogfood Gate: Team Loop Proof" in plan
    assert "### Phase 4: Auto-Curation And Knowledge Decay" in plan
    assert "Do not add these without an explicit privacy design" in plan
    assert "Gated future bets" in plan
    assert "Current Next Step" in plan


def test_adversarial_hardening_matrix_tracks_quality_plan_scenarios() -> None:
    doc = (ROOT / "docs" / "pre-release-adversarial-hardening.md").read_text(encoding="utf-8")
    scenarios = [
        "Duplicate Jurati global and project MCP config",
        "Duplicate non-Jurati MCP config",
        "Missing `JURATI_KNOWLEDGE_REMOTE`",
        "Unwritable `JURATI_CACHE_DIR`",
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

    assert "ready to move to a first external-user candidate" in doc
    assert "583 passed, 1 skipped" in doc
    assert "scripts/pre-release-installed-package-smoke.sh --keep" in doc
    assert "scripts/pre-release-single-repo-dogfood.sh --keep" in doc
    assert "scripts/pre-release-multi-repo-dogfood.sh --keep" in doc
    assert "scripts/pre-release-adversarial-smoke.sh" in doc
    assert "f60347ff-8457-46e3-ac25-0008b52e5f53" in doc
    assert "#43 Pre-release quality plan" in doc
    assert "#19 Roadmap: make Jurati ambient in daily agent work" in doc


def test_adversarial_smoke_script_runs_named_validation_owners() -> None:
    script = (ROOT / "scripts" / "pre-release-adversarial-smoke.sh").read_text(encoding="utf-8")

    assert "test_doctor_detects_global_project_server_name_collision" in script
    assert "test_doctor_does_not_block_on_unrelated_server_name_collision" in script
    assert "test_serve_check_missing_remote_fails" in script
    assert "test_doctor_check_startup_explains_unusable_cache_dir" in script
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
    assert "JURATI_PR_SIGNAL_FIXTURE" in clients
    assert "Do not set `HOME=/tmp/...` for Claude Code" in clients
    assert "Before reading files" in claude
    assert "hard precondition" in claude
    assert "should not proceed from local-only context" in claude
    assert "Never expose Jurati internals" in claude
    assert "entry IDs, branch names, ref paths, PR numbers" in claude
    assert "mcp__jurati-a1b2c3d4__sync" in claude


def test_team_readiness_ci_path_is_documented_and_smoked() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    clients = (ROOT / "docs" / "clients.md").read_text(encoding="utf-8")

    assert "jurati doctor --team --strict" in ci
    assert "jurati doctor --team --strict" in clients
    assert ".jurati/config.yaml" in clients
    assert "does not call the knowledge repo" in clients
    assert "does not report teammate installation" in clients


def test_first_user_trial_script_documents_expected_agent_behavior() -> None:
    script = (ROOT / "scripts" / "pre-release-first-user-trial.sh").read_text(encoding="utf-8")

    assert "onboard" in script
    assert "--knowledge-repo" in script
    assert "--project-repo" in script
    assert "--pack engineering" in script
    assert "doctor --check-startup" in script
    assert "Ready for `jurati serve`: yes" in script
    assert 'HOME="$home_dir"' in script
    assert "Prompt Battery" in script
    assert "hard precondition" in script
    assert "must not inspect git state" in script
    assert "Local-only context is not treated as an acceptable substitute" in script
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
    assert "active_refs_enabled=False" in script


def test_multi_repo_dogfood_harness_documents_coordination_signal() -> None:
    script = (ROOT / "scripts" / "pre-release-multi-repo-dogfood.sh").read_text(encoding="utf-8")

    assert "ostinato-dogfood/auth-api" in script
    assert "ostinato-dogfood/web-app" in script
    assert "pr-signals.json" in script
    assert "JURATI_PR_SIGNAL_FIXTURE" in script
    assert "context_goal_only" in script
    assert "context_path_specific" in script
    assert "pause" in script
    assert "developer_summary" in script
    assert "active_refs_enabled=False" in script


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
    assert "manual connected-agent coordination gate passed" in doc
    assert "f60347ff-8457-46e3-ac25-0008b52e5f53" in doc
    assert "Goal-only startup context returned a coordination effect: `revise`" in doc
    assert "Path-specific context returned a coordination effect: `pause`" in doc
    assert "Alice's upstream auth contract PR should be accounted for" in doc
    assert "fixture-backed PR-signal source" in doc


def test_dogfood_gate_run_tracks_current_roadmap_issue() -> None:
    doc = (ROOT / "docs" / "dogfood-gate-runs.md").read_text(encoding="utf-8")
    build_plan = (ROOT / "docs" / "build-plan.md").read_text(encoding="utf-8")

    assert "https://github.com/ostinato-forge/jurati/issues/90" in doc
    assert "active_refs_enabled: false" in doc
    assert "connected-agent-stream.jsonl" in doc
    assert "28d46868-31aa-463c-ae51-2731ea746ca1" in doc
    assert "8e2f015e-963f-4ffb-8324-772bba4a47f4" in doc
    assert "mcp__jurati-e2635254__sync" in doc
    assert "mcp__jurati-e2635254__context" in doc
    assert "mcp__jurati-3d021062__sync" in doc
    assert "mcp__jurati-3d021062__context" in doc
    assert "auth-api PR `#7`" in doc
    assert "sync -> context -> planning" in doc
    assert "broader connected-agent pass" in doc
    assert "dogfood-gate-runs.md" in build_plan
