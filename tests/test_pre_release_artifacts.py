from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pre_release_build_plan_tracks_quality_plan_and_issue() -> None:
    plan = (ROOT / "docs" / "pre-release-build-plan.md").read_text(encoding="utf-8")

    assert "https://github.com/ostinato-forge/jurati/issues/43" in plan
    assert "Status: Complete" in plan
    assert "All 6 workstreams passed" in plan
    assert "Reproducible first-user trial" in plan
    assert "Multi-repo coordination test" in plan


def test_forward_build_plan_tracks_next_execution_order() -> None:
    plan = (ROOT / "docs" / "build-plan.md").read_text(encoding="utf-8")

    assert "What's Shipped (v1.3.0)" in plan
    assert "Road to Production" in plan
    assert "Step 1: Testing" in plan
    assert "Real Team Loop" in plan
    assert "Step 2: Fix What Testing Finds" in plan
    assert "Step 3: Remaining Polish" in plan
    assert "Future Work (Post-Production)" in plan
    assert "Gated behind testing evidence" in plan
    assert "Product Guardrails" in plan
    assert "Security, Privacy, And Content Safety Gate" in plan
    assert "security-privacy-content-safety.md" in plan
    assert "Current Next Step" in plan
    assert "https://github.com/ostinato-forge/jurati/issues/89" in plan


def test_trust_gate_docs_make_security_privacy_content_safety_release_blocking() -> None:
    gate = (ROOT / "docs" / "security-privacy-content-safety.md").read_text(encoding="utf-8")
    audit = (ROOT / "docs" / "security-privacy-content-safety-audit.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    quality = (ROOT / "docs" / "pre-release-quality-plan.md").read_text(encoding="utf-8")

    assert "If it fails that boundary even" in gate
    assert "more features do not matter." in gate
    assert "A confusing or scary agent-terminal response is a trust failure." in gate
    assert "#96 Content safety and write auditability" in gate
    assert "#95 Metrics" in gate
    assert "Next Build" in audit
    assert "imports now also reject default content-policy block/review matches" in audit
    assert "connected-agent active-context privacy evidence" in audit
    assert "Security, privacy, and content safety are release gates" in readme
    assert "open P0 findings" in release
    assert "pre-release-active-context-privacy-smoke.sh" in release
    assert "Content-Safety Acceptance Criteria" in quality


def test_adversarial_hardening_matrix_tracks_quality_plan_scenarios() -> None:
    doc = (ROOT / "docs" / "pre-release-adversarial-hardening.md").read_text(encoding="utf-8")
    scenarios = [
        "Duplicate Jurati global and project MCP config",
        "Duplicate non-Jurati MCP config",
        "Missing `JURATI_KNOWLEDGE_REMOTE`",
        "Unwritable `JURATI_CACHE_DIR`",
        "Unavailable GitHub auth",
        "Stale active context",
        "Expired or restricted active context in startup payload",
        "Conflicting decisions",
        "Restricted entry linked by public entry",
        "Bad context pack tarball layout",
        "Context pack with secrets or review-triggering content",
        "Labeled PR with unavailable changed paths",
        "Unlabeled relevant PR",
        "Agent asks user to run raw MCP JSON",
        "Agent exposes entry IDs or ref paths",
        "Agent skips startup context",
        "Active context enabled by surprise",
        "Active context accepts review-triggering content",
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
    assert 'PYTHONPATH="$repo_root/src' in script
    assert "test_doctor_does_not_block_on_unrelated_server_name_collision" in script
    assert "test_serve_check_missing_remote_fails" in script
    assert "test_doctor_check_startup_explains_unusable_cache_dir" in script
    assert "test_no_token_skips_api_candidate" in script
    assert "test_query_excludes_expired_by_default" in script
    assert "test_context_excludes_expired_and_restricted_active_entries" in script
    assert "test_generate_static_html_hides_restricted_link_targets" in script
    assert "test_plan_context_import_rejects_secret_content" in script
    assert "test_plan_context_import_rejects_content_policy_review_content" in script
    assert "test_missing_paths_status_surfaces_clarify_guidance" in script
    assert "test_active_record_requires_repo_policy_opt_in" in script
    assert "test_creates_claude_md" in script


def test_active_context_privacy_smoke_is_release_owned() -> None:
    script = (ROOT / "scripts" / "pre-release-active-context-privacy-smoke.sh").read_text(
        encoding="utf-8"
    )
    dogfood = (ROOT / "docs" / "dogfood-gate-runs.md").read_text(encoding="utf-8")

    assert "test_active_record_requires_repo_policy_opt_in" in script
    assert "test_active_refs_disabled_skips_overlay" in script
    assert "test_overlays_active_refs" in script
    assert "test_mcp_config_write_project_carries_repo_active_refs_policy" in script
    assert "test_mcp_config_write_project_rejects_invalid_repo_ttl" in script
    assert "test_active_record_defaults_expiry_from_policy_ttl" in script
    assert "test_active_record_rejects_expiry_beyond_policy_ttl" in script
    assert "test_active_record_rejects_review_required_content" in script
    assert "test_context_excludes_expired_and_restricted_active_entries" in script
    assert "Active Context Privacy Gate" in dogfood
    assert "connected-agent active-context" in dogfood


def test_shareable_note_export_fixture_has_user_smoke_script() -> None:
    script = (ROOT / "scripts" / ("obs" + "idian-import-user-smoke.sh")).read_text(encoding="utf-8")
    fixture = ROOT / "docs" / "examples" / "shareable-note-export"

    assert "shareable-note-export" in script
    assert "--mode obs" + "idian" in script
    assert "Summary: 6 create, 5 skip, 2 reject" in script
    assert "Summary: 6 create, 0 skip, 0 reject" in script
    assert (fixture / "manifest.json").exists()
    assert (fixture / "Repos" / "api-service.md").exists()
    assert (fixture / "Tools" / "deploy-cli.md").exists()
    assert (fixture / "Errors" / "ci-cache-loop.md").exists()
    assert (fixture / "Private Notes" / "local-handoff.md").exists()


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
    assert "Follow any verdict" in claude
    assert "read_many()" in claude
    assert "Do not bulk-read every entry" in claude
    assert "Never expose Jurati internals" in claude
    assert "entry IDs, branch names, ref paths, PR numbers" in claude
    assert "mcp__jurati__read_many" in claude
    assert "mcp__jurati-a1b2c3d4__sync" in claude


def test_team_readiness_ci_path_is_documented_and_smoked() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    clients = (ROOT / "docs" / "clients.md").read_text(encoding="utf-8")
    adoption = (ROOT / "docs" / "adoption.md").read_text(encoding="utf-8")

    assert "jurati doctor --team --strict" in ci
    assert "jurati doctor --team --strict" in clients
    assert "jurati doctor --team --check-startup --strict" in clients
    assert "jurati doctor --team --check-startup --strict" in adoption
    assert ".jurati/config.yaml" in clients
    assert "does not call the knowledge repo" in clients
    assert "does not report teammate installation" in clients
    assert "Fresh teammate clone" in adoption


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
    assert "pre-release-teammate-clone-smoke.sh" in script
    assert 'env JURATI_BIN="$installed_jurati"' in script
    assert "Jurati first-user trial setup passed." in script
    assert "Fresh-clone teammate smoke passed." in script
    assert "Ready for `jurati serve`: yes" in script


def test_teammate_clone_smoke_proves_fresh_clone_one_command_path() -> None:
    script = (ROOT / "scripts" / "pre-release-teammate-clone-smoke.sh").read_text(encoding="utf-8")

    assert "git clone --quiet" in script
    assert "onboard" in script
    assert '--command "$JURATI_BIN"' in script
    assert 'JURATI_KNOWLEDGE_REMOTE=""' in script
    assert "doctor --team --check-startup --strict" in script
    assert "serve --check" in script
    assert "repo participation marker: yes" in script
    assert "project MCP config:        yes" in script
    assert "read-only tools:           yes" in script
    assert "no teammate install/presence tracking" in script
    assert "tools/call" in script
    assert "Fresh-clone teammate smoke passed." in script


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
    assert "import-docs" in script
    assert "--mode adr" in script
    assert "--mode docs" in script
    assert "JURATI_CURATION_WRITE=true" in script
    assert "context_curation" in script
    assert "completed_artifact_revalidation" in script
    assert '--command "$JURATI_BIN"' in script
    assert "pr-signals.json" in script
    assert "JURATI_PR_SIGNAL_FIXTURE" in script
    assert "context_goal_only" in script
    assert "context_path_specific" in script
    assert "pause" in script
    assert "developer_summary" in script
    assert "active_refs_enabled=False" in script


def test_dogfood_gate_run_records_import_curation_and_connected_agent() -> None:
    doc = (ROOT / "docs" / "dogfood-gate-runs.md").read_text(encoding="utf-8")

    assert "2026-05-26: Import And Curation Gate" in doc
    assert "jurati/import-docs-auth-contract" in doc
    assert "jurati/import-docs-web-context" in doc
    assert "jurati/curation/dogfood-import-loop" in doc
    assert "mcp__jurati-235c7204__sync" in doc
    assert "mcp__jurati-235c7204__context" in doc
    assert "Shared auth contract is owned upstream" in doc
    assert "rotationPolicy: server-driven" in doc
    assert "workspace-boundary" in doc
    assert "permission" in doc


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
