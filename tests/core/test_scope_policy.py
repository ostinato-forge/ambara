# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for local Ambara scope mute policy."""

from __future__ import annotations

from datetime import UTC, datetime

from ambara.core.index import Index
from ambara.core.pr_signals import PRSignal
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    SourceMeta,
)
from ambara.core.scope_policy import (
    ScopeMutePolicy,
    filter_index,
    filter_signals,
    filter_source_inputs,
    is_entry_muted,
    is_signal_muted,
    is_source_input_muted,
)
from ambara.sources.adapters import source_artifact_from_pr_signal

NOW = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)


def _entry(
    entry_id: str,
    *,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    source_repo: str | None = None,
) -> Entry:
    return Entry(
        path=f"decisions/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title=f"Entry {entry_id}",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            projects=projects or [],
            tags=tags or [],
            source=(
                SourceMeta(repo=source_repo, commit="abc123") if source_repo is not None else None
            ),
        ),
        body="Shared context.",
    )


def _signal(repo: str = "org/api", **overrides: object) -> PRSignal:
    data: dict[str, object] = {
        "signal_id": "github:org/api:pull:42",
        "provider": "github",
        "repo": repo,
        "number": 42,
        "url": "https://github.com/org/api/pull/42",
        "title": "Update project context",
        "body_excerpt": None,
        "author": "alice",
        "state": "open",
        "labels": ("ambara",),
        "created_at": NOW,
        "updated_at": NOW,
        "merged_at": None,
        "changed_paths": ("src/app.py",),
        "target_areas": ("src",),
    }
    data.update(overrides)
    return PRSignal(**data)  # type: ignore[arg-type]


def test_scope_policy_normalizes_and_merges_values() -> None:
    policy = ScopeMutePolicy.from_raw(
        {
            "projects": [" LEGACY-PROJ ", "legacy-proj"],
            "repos": ["Org/API"],
            "signal_sources": [" GitHub "],
            "source_inputs": [" Jira "],
            "tags": ["Done"],
        }
    )

    assert policy.projects == ("legacy-proj",)
    assert policy.repos == ("org/api",)
    assert policy.signal_sources == ("github", "jira")
    assert policy.source_inputs == ("github", "jira")
    assert policy.tags == ("done",)
    assert policy.count() == 5
    assert policy.to_dict() == {
        "projects": ["legacy-proj"],
        "repos": ["org/api"],
        "signal_sources": ["github", "jira"],
        "tags": ["done"],
    }


def test_entry_policy_matches_project_tag_and_source_repo() -> None:
    policy = ScopeMutePolicy(
        projects=("legacy-proj",),
        repos=("org/api",),
        tags=("stale",),
    )

    assert is_entry_muted(_entry("project", projects=["LEGACY-PROJ"]), policy)
    assert is_entry_muted(_entry("tagged", tags=["stale"]), policy)
    assert is_entry_muted(_entry("source", source_repo="org/api"), policy)
    assert not is_entry_muted(_entry("current", projects=["current"]), policy)


def test_signal_policy_matches_repo_label_provider_and_target_area() -> None:
    policy = ScopeMutePolicy(
        projects=("auth",),
        repos=("org/api",),
        signal_sources=("github",),
        tags=("ambara",),
    )

    assert is_signal_muted(_signal("org/api"), policy)
    assert is_signal_muted(_signal("org/web", labels=("ambara",)), policy)
    assert is_signal_muted(_signal("org/web", target_areas=("auth",)), policy)
    assert is_signal_muted(_signal("org/web", provider="github"), policy)
    assert not is_signal_muted(
        _signal("org/web", provider="gitlab", labels=("other",), target_areas=("web",)),
        ScopeMutePolicy(projects=("auth",), repos=("org/api",), tags=("ambara",)),
    )


def test_source_input_policy_alias_matches_provider() -> None:
    policy = ScopeMutePolicy.from_raw({"source_inputs": ["GitHub"]})

    assert policy.source_inputs == ("github",)
    assert is_source_input_muted(_signal("org/web", provider="github"), policy)
    assert policy.to_dict() == {"signal_sources": ["github"]}


def test_signal_policy_preserves_source_input_compatibility_alias() -> None:
    policy = ScopeMutePolicy(repos=("org/api",))
    signal = _signal("org/api")

    assert is_source_input_muted(signal, policy)
    assert is_signal_muted(signal, policy) == is_source_input_muted(signal, policy)


def test_filters_remove_muted_entries_and_signals() -> None:
    current = _entry("current", projects=["current"])
    muted = _entry("muted", projects=["LEGACY-PROJ"])
    index = Index({"current": current, "muted": muted})
    policy = ScopeMutePolicy(projects=("legacy-proj",), repos=("org/old",))

    filtered_index = filter_index(index, policy)
    filtered_signals = filter_signals(
        [_signal("org/current"), _signal("org/old")],
        policy,
    )

    assert set(filtered_index.entries) == {"current"}
    assert [signal.repo for signal in filtered_signals] == ["org/current"]


def test_filter_signals_preserves_source_input_compatibility_alias() -> None:
    inputs = [_signal("org/current"), _signal("org/old")]
    policy = ScopeMutePolicy(repos=("org/old",))

    assert filter_signals(inputs, policy) == filter_source_inputs(inputs, policy)


def test_scope_policy_summary_exposes_source_inputs_with_signal_compatibility() -> None:
    from ambara.core.scope_policy import scope_policy_summary

    summary = scope_policy_summary(ScopeMutePolicy(signal_sources=("github",)))

    assert summary["source_inputs"] == ["github"]
    assert summary["signal_sources"] == ["github"]


def test_source_artifact_policy_matches_repo_label_provider_and_target_area() -> None:
    current = source_artifact_from_pr_signal(
        _signal(
            "org/current",
            signal_id="github:org/current:pull:42",
            url="https://github.com/org/current/pull/42",
        ),
        fetched_at=NOW,
    )
    muted_repo = source_artifact_from_pr_signal(_signal("org/api"), fetched_at=NOW)
    muted_area = source_artifact_from_pr_signal(
        _signal("org/web", labels=("other",), target_areas=("auth",)),
        fetched_at=NOW,
    )
    policy = ScopeMutePolicy(
        projects=("auth",),
        repos=("org/api",),
        signal_sources=("github",),
        tags=("ambara",),
    )

    assert is_source_input_muted(muted_repo, policy)
    assert is_source_input_muted(muted_area, ScopeMutePolicy(projects=("auth",)))
    assert not is_source_input_muted(current, ScopeMutePolicy(repos=("org/api",), tags=("other",)))

    filtered = filter_source_inputs(
        [current, muted_repo],
        ScopeMutePolicy(repos=("org/api",)),
    )

    assert [artifact.artifact_id for artifact in filtered] == [current.artifact_id]
