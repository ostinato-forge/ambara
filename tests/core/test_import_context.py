from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from jurati.core.import_context import (
    ContextPackError,
    plan_context_import,
    plan_markdown_import,
)

NOW = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _write_bundle(tmp_path: Path, manifest: dict[str, object], files: dict[str, str]) -> Path:
    return _write_bundle_with_prefix(tmp_path, manifest, files)


def _write_bundle_with_prefix(
    tmp_path: Path,
    manifest: dict[str, object],
    files: dict[str, str],
    *,
    member_prefix: str = "",
) -> Path:
    bundle = tmp_path / "context-pack.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        _add_text(tar, _prefixed_path("manifest.json", member_prefix), json.dumps(manifest))
        for path, content in files.items():
            _add_text(tar, _prefixed_path(path, member_prefix), content)
    return bundle


def _add_text(tar: tarfile.TarFile, path: str, content: str) -> None:
    data = content.encode("utf-8")
    info = tarfile.TarInfo(path)
    info.size = len(data)
    tar.addfile(info, BytesIO(data))


def _prefixed_path(path: str, member_prefix: str) -> str:
    if not member_prefix:
        return path
    if member_prefix == ".":
        return f"./{path}"
    return f"{member_prefix}/{path}"


def test_plan_context_import_maps_source_categories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle(
        tmp_path,
        {
            "schema_version": 1,
            "name": "Team Pack",
            "items": [
                {
                    "path": "Repos/api.md",
                    "category": "repo profile",
                    "id": "api-service",
                    "title": "API Service",
                    "projects": ["api"],
                },
                {
                    "path": "Tools/ruff.md",
                    "category": "tool note",
                    "id": "use-ruff",
                    "title": "Use Ruff",
                },
            ],
        },
        {
            "Repos/api.md": "Current repo operating context.",
            "Tools/ruff.md": "Run Ruff before opening review.",
        },
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.valid
    assert plan.create_count == 2
    first, second = plan.actions
    assert first.destination_path == "projects/api-service.md"
    assert first.entry is not None
    assert first.entry.frontmatter.type == "project"
    assert first.entry.frontmatter.level == "L1"
    assert "context-pack" in first.entry.frontmatter.tags
    assert "Source path: Repos/api.md" in first.entry.body
    assert second.destination_path == "workflows/use-ruff.md"


def test_plan_context_import_accepts_dot_prefixed_tar_members(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle_with_prefix(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Repos/api.md",
                    "category": "repo profile",
                    "id": "api-service",
                    "title": "API Service",
                }
            ],
        },
        {"Repos/api.md": "Current repo operating context."},
        member_prefix=".",
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.valid
    assert plan.create_count == 1


def test_plan_context_import_accepts_single_root_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle_with_prefix(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Repos/api.md",
                    "category": "repo profile",
                    "id": "api-service",
                    "title": "API Service",
                }
            ],
        },
        {"Repos/api.md": "Current repo operating context."},
        member_prefix="context-pack",
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.valid
    assert plan.create_count == 1


def test_plan_context_import_skips_existing_ids(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "projects").mkdir(parents=True)
    (repo / "projects" / "api-service.md").write_text(
        """\
---
schema_version: 1
id: api-service
title: API Service
type: project
level: L1
status: proposed
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: []
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Existing context.
"""
    )
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Repos/api.md",
                    "category": "repo profile",
                    "id": "api-service",
                    "title": "API Service",
                }
            ],
        },
        {"Repos/api.md": "New context."},
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.create_count == 0
    assert plan.skip_count == 1
    assert plan.actions[0].reason == "entry id already exists"


def test_plan_context_import_rejects_untrusted_items(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Notes/unknown.md",
                    "category": "misc",
                    "id": "unknown-note",
                    "title": "Unknown",
                },
                {
                    "path": "Notes/restricted.md",
                    "category": "decision",
                    "id": "restricted-note",
                    "title": "Restricted",
                    "sensitivity": "restricted",
                },
                {
                    "path": "Personal/local.md",
                    "category": "tool note",
                    "id": "local-note",
                    "title": "Local",
                },
                {
                    "path": "Notes/bad-id.md",
                    "category": "decision",
                    "id": "Bad ID",
                    "title": "Bad ID",
                },
            ],
        },
        {
            "Notes/unknown.md": "Body.",
            "Notes/restricted.md": "Body.",
            "Personal/local.md": "Body.",
            "Notes/bad-id.md": "Body.",
        },
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.reject_count == 4
    reasons = [action.reason for action in plan.actions]
    assert "unknown category 'misc'" in reasons
    assert "restricted content cannot be imported by context pack dry-run" in reasons
    assert "personal or local-only source" in reasons
    assert "generated frontmatter failed validation" in reasons


def test_plan_context_import_rejects_secret_content(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Decisions/token.md",
                    "category": "decision",
                    "id": "token-decision",
                    "title": "Token Decision",
                }
            ],
        },
        {"Decisions/token.md": "Do not import this. password=hunter2"},
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.reject_count == 1
    assert plan.actions[0].reason == "source content appears to contain secrets"


def test_plan_context_import_rejects_unresolved_links(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Decisions/link.md",
                    "category": "decision",
                    "id": "link-decision",
                    "title": "Link Decision",
                }
            ],
        },
        {"Decisions/link.md": "Depends on [[missing-entry]]."},
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.reject_count == 1
    assert plan.actions[0].reason == "generated entry has unresolved links"
    assert "unresolved wiki link to 'missing-entry'" in plan.actions[0].errors


def test_plan_context_import_rejects_bad_source_frontmatter(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _write_bundle(
        tmp_path,
        {
            "name": "Team Pack",
            "items": [
                {
                    "path": "Decisions/bad.md",
                    "category": "decision",
                    "id": "bad-source",
                    "title": "Bad Source",
                }
            ],
        },
        {"Decisions/bad.md": "---\ntitle: [unterminated\n---\nBody."},
    )

    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.reject_count == 1
    assert plan.actions[0].reason == "source frontmatter parse error"


def test_plan_markdown_import_maps_adr_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "docs" / "adr"
    source.mkdir(parents=True)
    (source / "0001-use-postgres.md").write_text(
        "# Use Postgres\n\nPrefer Postgres for the API data store.\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    plan = plan_markdown_import(
        [source],
        knowledge_repo=repo,
        now=NOW,
        mode="adr",
        projects=("api",),
        tags=("database",),
        source_root=project,
    )

    assert plan.valid
    assert plan.create_count == 1
    action = plan.actions[0]
    assert action.destination_path == "decisions/use-postgres.md"
    assert action.entry is not None
    assert action.entry.frontmatter.type == "decision"
    assert action.entry.frontmatter.level == "L2"
    assert action.entry.frontmatter.projects == ["api"]
    assert action.entry.frontmatter.tags == [
        "adr",
        "database",
        "markdown-import",
        "decision",
    ]
    assert "Prefer Postgres" in action.entry.body
    assert "Markdown import: adr markdown" in action.entry.body
    assert "Source path: docs/adr/0001-use-postgres.md" in action.entry.body


def test_plan_markdown_import_maps_docs_mode(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()
    (source / "architecture.md").write_text(
        "# Architecture\n\nCurrent project architecture.\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    plan = plan_markdown_import([source], knowledge_repo=repo, now=NOW, mode="docs")

    assert plan.valid
    assert plan.actions[0].destination_path == "projects/architecture.md"
    assert plan.actions[0].entry is not None
    assert plan.actions[0].entry.frontmatter.type == "project"
    assert plan.actions[0].entry.frontmatter.tags == [
        "docs",
        "markdown-import",
        "project",
    ]


def test_plan_markdown_import_accepts_absolute_sources(tmp_path: Path) -> None:
    source = tmp_path / "source-docs"
    source.mkdir()
    (source / "rfc-cache.md").write_text("# Cache RFC\n\nUse Redis.\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    plan = plan_markdown_import(
        [source],
        knowledge_repo=repo,
        now=NOW,
        mode="rfc",
    )

    assert plan.valid
    assert plan.actions[0].destination_path == "decisions/cache-rfc.md"
    assert plan.actions[0].entry is not None
    assert "Source path: source-docs/rfc-cache.md" in plan.actions[0].entry.body


def test_plan_markdown_import_skips_nested_hidden_paths(tmp_path: Path) -> None:
    source = tmp_path / ".workspace" / "docs"
    source.mkdir(parents=True)
    (source / "keep.md").write_text("# Keep\n\nImport this.\n", encoding="utf-8")
    hidden_dir = source / ".drafts"
    hidden_dir.mkdir()
    (hidden_dir / "skip.md").write_text("# Skip\n\nDo not import.\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    plan = plan_markdown_import([source], knowledge_repo=repo, now=NOW)

    assert plan.valid
    assert plan.create_count == 1
    assert plan.actions[0].source_path == "docs/keep.md"


def test_plan_markdown_import_rejects_invalid_utf8(tmp_path: Path) -> None:
    source = tmp_path / "bad.md"
    source.write_bytes(b"\xff\xfe\x00")
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ContextPackError, match="UTF-8"):
        plan_markdown_import([source], knowledge_repo=repo, now=NOW)


def test_plan_markdown_import_rejects_empty_directories(tmp_path: Path) -> None:
    source = tmp_path / "docs"
    source.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ContextPackError, match="no Markdown files"):
        plan_markdown_import([source], knowledge_repo=repo, now=NOW)


def test_plan_markdown_import_rejects_non_markdown_files(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("not Markdown", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ContextPackError, match="not a Markdown file"):
        plan_markdown_import([source], knowledge_repo=repo, now=NOW)


def test_plan_context_import_requires_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "bad.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        _add_text(tar, "Notes/note.md", "Body")

    with pytest.raises(ContextPackError, match="manifest.json"):
        plan_context_import(bundle, knowledge_repo=tmp_path, now=NOW)


def test_example_context_pack_is_valid(tmp_path: Path) -> None:
    example = ROOT / "docs" / "examples" / "context-pack"
    bundle = tmp_path / "example.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for path in sorted(item for item in example.rglob("*") if item.is_file()):
            tar.add(path, arcname=path.relative_to(example).as_posix())

    repo = tmp_path / "repo"
    repo.mkdir()
    plan = plan_context_import(bundle, knowledge_repo=repo, now=NOW)

    assert plan.valid
    assert plan.create_count == 2
