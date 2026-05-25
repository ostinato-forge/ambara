from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRODUCT_SURFACES = [
    ROOT / "README.md",
    ROOT / "docs" / "adoption.md",
    ROOT / "docs" / "jurati-deck.html",
    ROOT / "docs" / "jurati-tech-deck.html",
    ROOT / "src" / "jurati" / "cli.py",
    ROOT / "src" / "jurati" / "server.py",
]


def test_product_claim_uses_context_not_shared_memory() -> None:
    for path in PRODUCT_SURFACES:
        text = path.read_text(encoding="utf-8").lower()
        assert "shared team memory" not in text, path
        assert "shared memory" not in text, path
        assert "memory backed by git" not in text, path


def test_context_boundary_doc_defines_storage_model() -> None:
    text = (ROOT / "docs" / "context-not-memory.md").read_text(encoding="utf-8")

    assert "Jurati is a shared agent context layer" in text
    assert "Markdown + YAML" in text
    assert "Human-reviewable source of truth in git" in text
    assert "Query stores are derived" in text
    assert "indexes that can be rebuilt" in text
    assert "shared Markdown context workflow" in text
    assert "general-purpose personal notes app" in text


def test_context_packs_plan_keeps_spike_inside_jurati_architecture() -> None:
    text = (ROOT / "docs" / "context-packs-plan.md").read_text(encoding="utf-8")

    assert "Jurati Markdown repo = reviewed team context" in text
    assert "Context packs = import and migration format" in text
    assert "Build a pure `jurati.core.graph` module." in text
    assert "Add `jurati import-context <bundle> --dry-run`." in text
    assert "Add `jurati html <knowledge-repo>`." in text
    assert "SQLite as rebuildable from the git knowledge repo" in text


def test_context_pack_migration_doc_preserves_product_boundary() -> None:
    text = (ROOT / "docs" / "context-pack-migration.md").read_text(encoding="utf-8")

    assert "not trying to import a personal vault wholesale" in text
    assert "jurati import-context --dry-run" in text
    assert "creates a review branch" in text
    assert "restricted entries" in text
    assert (ROOT / "docs" / "examples" / "context-pack" / "manifest.json").exists()


def test_repo_avoids_legacy_note_app_brand_reference() -> None:
    forbidden = "obs" + "idian"
    allowed_source_specific_mentions = {
        ROOT / "docs" / "build-plan.md",
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
