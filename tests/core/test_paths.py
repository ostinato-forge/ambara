# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import pytest

from ambara.core.paths import active_ref, entry_path, is_safe_path
from ambara.core.schema import EntryType


def test_entry_path_is_derived_from_type_and_id() -> None:
    assert entry_path(EntryType.PRINCIPLE, "deterministic-core") == (
        "principles/deterministic-core.md"
    )


@pytest.mark.parametrize("entry_id", ["../escape", "NoCaps", "ab"])
def test_entry_path_rejects_invalid_ids(entry_id: str) -> None:
    with pytest.raises(ValueError):
        entry_path(EntryType.PROJECT, entry_id)


def test_active_ref_uses_configured_prefix_client_and_id() -> None:
    assert active_ref("ambara/active", "codex", "work-session") == (
        "refs/heads/ambara/active/codex/work-session"
    )


@pytest.mark.parametrize("client", ["ed.par", "../escape", "ab"])
def test_active_ref_rejects_invalid_client_slugs(client: str) -> None:
    with pytest.raises(ValueError):
        active_ref("ambara/active", client, "work-session")


@pytest.mark.parametrize("entry_id", ["../escape", "NoCaps", "ab"])
def test_active_ref_rejects_invalid_entry_ids(entry_id: str) -> None:
    with pytest.raises(ValueError, match="Invalid entry ID"):
        active_ref("ambara/active", "codex", entry_id)


@pytest.mark.parametrize("candidate", ["projects/status.md", "active/codex/work.md"])
def test_is_safe_path_accepts_relative_paths_under_root(candidate: str) -> None:
    assert is_safe_path("/knowledge", candidate)


@pytest.mark.parametrize("candidate", ["../secret.md", "projects/../../secret.md", "/tmp/x.md"])
def test_is_safe_path_rejects_traversal_or_absolute_paths(candidate: str) -> None:
    assert not is_safe_path("/knowledge", candidate)
