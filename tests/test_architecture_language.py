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
        "docs/install-troubleshooting.md",
        "docs/package-split-plan.md",
        "docs/pypi-trusted-publisher.md",
        "docs/release-proof.md",
        "docs/release-v0.5.0.md",
        "docs/release-v0.5.1.md",
    }


def test_readme_points_to_public_docs_only() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/install-troubleshooting.md" in text
    assert "docs/examples" not in text
    assert "docs/guide.md" not in text
    assert "docs/clients.md" not in text
    assert "docs/context-not-memory.md" not in text


def test_readme_support_matrix_states_current_truth() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "### Support Matrix" in text
    assert "GitHub pull requests and GitLab merge requests are first-class." in text
    assert "Other git hosts" in text


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
