"""v1 backward compatibility — parse-time defaults, not data migration."""

from __future__ import annotations

from jurati.core.index import parse_entry
from jurati.core.schema import Visibility


def test_v1_entry_keeps_version_1_gains_v2_defaults() -> None:
    """v1 entries are not normalized to v2. The version stays 1, and
    Pydantic applies defaults for absent v2 fields."""
    raw = {
        "schema_version": 1,
        "id": "legacy-entry",
        "title": "Legacy",
        "type": "project",
        "level": "L1",
        "status": "proposed",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    entry = parse_entry("projects/legacy-entry.md", raw, "old body")
    assert entry.frontmatter.schema_version == 1
    assert entry.frontmatter.visibility == Visibility.INTERNAL
    assert entry.frontmatter.recorded_by is None


def test_v2_entry_preserves_explicit_visibility() -> None:
    raw = {
        "schema_version": 2,
        "id": "new-entry",
        "title": "New",
        "type": "decision",
        "level": "L2",
        "status": "proposed",
        "created_at": "2026-05-05T00:00:00Z",
        "updated_at": "2026-05-05T00:00:00Z",
        "visibility": "external",
    }
    entry = parse_entry("decisions/new-entry.md", raw, "new body")
    assert entry.frontmatter.schema_version == 2
    assert entry.frontmatter.visibility == Visibility.EXTERNAL
