# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRODUCT_SURFACES = [
    ROOT / "README.md",
    ROOT / "product-and-tech-slides.html",
    ROOT / "src" / "ambara" / "cli.py",
    ROOT / "src" / "ambara" / "server.py",
]


def test_product_claim_uses_context_not_shared_memory() -> None:
    for path in PRODUCT_SURFACES:
        text = path.read_text(encoding="utf-8").lower()
        assert "shared team memory" not in text, path
        assert "shared memory" not in text, path
        assert "memory backed by git" not in text, path


def test_public_docs_are_minimal() -> None:
    docs = {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "docs").glob("**/*") if path.is_file()
    }

    assert docs == {
        "docs/agent-operating-policy.md",
        "docs/decisions/0001-source-artifact-schema-freeze.md",
        "docs/install-troubleshooting.md",
        "docs/package-split-plan.md",
        "docs/pypi-trusted-publisher.md",
        "docs/release-proof.md",
        "docs/release-v0.5.0.md",
        "docs/release-v0.5.1.md",
        "docs/release-v0.6.0.md",
        "docs/release-v0.7.0.md",
        "docs/source-providers.md",
    }


def test_readme_points_to_public_docs_only() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/install-troubleshooting.md" in text
    assert "docs/source-providers.md" in text
    assert "docs/signal-providers.md" not in text
    assert "docs/examples" not in text
    assert "docs/guide.md" not in text
    assert "docs/clients.md" not in text
    assert "docs/context-not-memory.md" not in text


def test_readme_support_matrix_states_current_truth() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### Support Matrix" in text
    assert "GitHub pull requests and GitLab merge requests are first-class." in text
    assert "Other git hosts" in text
    assert "| Sources | Source Preview built-ins are GitHub review artifacts" in text
    assert "### Project Source Inputs" in text
    assert "Sources/signals" not in text
    assert "Signal text" not in text
    assert "### Project Signals" not in text
    assert "Legacy entry-point signal providers remain a compatibility path" not in text
    assert "AMBARA_SOURCE_PROVIDER=gitlab" in text
    assert "AMBARA_SOURCE_REPOS=your-org/repo1,your-org/repo2" in text
    assert "`AMBARA_SOURCE_PROVIDER`" in text
    assert "`AMBARA_SOURCE_REPOS`" in text
    assert "`AMBARA_SOURCE_FIXTURE`" in text
    assert "Legacy `AMBARA_SIGNAL_PROVIDER` and `AMBARA_PR_SIGNAL_REPOS`" not in text
    assert "AMBARA_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2" not in text


def test_install_troubleshooting_uses_source_input_env_names() -> None:
    text = (ROOT / "docs" / "install-troubleshooting.md").read_text(encoding="utf-8")

    assert "### Review Or Jira Source Inputs Do Not Appear" in text
    assert "source-input path" in text
    assert "`AMBARA_SOURCE_PROVIDER`" in text
    assert "`AMBARA_SOURCE_REPOS`" in text
    assert "`AMBARA_SOURCE_FIXTURE`" in text
    assert "AMBARA_SOURCE_PROVIDER=gitlab" in text
    assert "AMBARA_SOURCE_PROVIDER=jira" in text
    assert "AMBARA_SOURCE_REPOS=your-group/repo1,your-group/repo2" in text
    assert "AMBARA_PR_SIGNAL_REPOS=your-group/repo1,your-group/repo2" not in text
    assert "AMBARA_SIGNAL_PROVIDER=jira" not in text


def test_source_provider_docs_state_current_contract_truth() -> None:
    text = (ROOT / "docs" / "source-providers.md").read_text(encoding="utf-8")

    assert "# Writing A Source Provider" in text
    assert "Provider packages are translators, not privacy bypasses." in text
    assert "Linear, Notion, and Confluence are v1-track Team Preview scope" in text
    assert "not Source Preview built-ins yet" in text
    assert "Not Source Preview support." in text


def test_public_source_claims_do_not_advertise_unbuilt_team_preview_sources() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    source_docs = (ROOT / "docs" / "source-providers.md").read_text(encoding="utf-8")
    release_proof = (ROOT / "docs" / "release-proof.md").read_text(encoding="utf-8")

    for provider in ("Linear", "Notion", "Confluence", "Slack", "Teams", "Sentry"):
        assert provider not in readme

    assert "| First-class Source Preview | `github`, `gitlab`, `jira`, `fixture` |" in (source_docs)
    assert "Planned Team Preview | Linear, Notion, Confluence" in source_docs
    assert "not publicly claimed as supported yet" in source_docs
    assert "Deferred | Slack, Teams, Sentry" in source_docs
    assert "Not Source Preview support" in source_docs
    assert "Source Preview must not publicly claim Linear, Notion, Confluence" in (release_proof)
    assert "broad workplace search" in release_proof
    assert "arbitrary privacy-safe third-party" in release_proof


def test_release_proof_mentions_gitlab_first_class_verification() -> None:
    text = (ROOT / "docs" / "release-proof.md").read_text(encoding="utf-8")

    assert "## v0.6.0 Multi-Forge Proof" in text
    assert "GitHub and GitLab are first-class review backends" in text


def test_repo_avoids_legacy_note_app_brand_reference() -> None:
    forbidden = "obs" + "idian"
    allowed_source_specific_mentions = {
        ROOT / "src" / "ambara" / "cli.py",
        ROOT / "src" / "ambara" / "import_context.py",
        ROOT / "tests" / "test_import_context.py",
        ROOT / "tests" / "test_cli.py",
    }
    paths = [
        *ROOT.glob("*.md"),
        *ROOT.glob("docs/**/*.md"),
        *ROOT.glob("docs/**/*.html"),
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("tests/**/*.py"),
    ]

    for path in paths:
        if path in allowed_source_specific_mentions:
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert forbidden not in text, path
