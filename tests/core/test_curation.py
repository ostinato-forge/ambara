# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.core.curation — contradiction detection and staleness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ambara.core.curation import (
    detect_contradictions,
    find_stale_entries,
    suggest_revalidation_from_signals,
)
from ambara.core.pr_signals import CoordinationSignal
from ambara.core.schema import EntryStatus, EntryType, EscalationLevel

from .conftest import BASE_NOW, make_entry


def _signal(**overrides: object) -> CoordinationSignal:
    defaults = {
        "signal_id": "github:org/api:pull:12",
        "provider": "github",
        "source": "org/api",
        "artifact_ref": "https://github.com/org/api/pull/12",
        "title": "Refactor auth token rotation",
        "excerpt": "Updates auth token rotation workflow.",
        "actor": "alice",
        "state": "merged",
        "labels": ("ambara", "security"),
        "created_at": BASE_NOW - timedelta(days=3),
        "updated_at": BASE_NOW - timedelta(days=1),
        "resolved_at": BASE_NOW - timedelta(days=1),
        "subject_refs": ("src/auth/tokens.py",),
        "subject_areas": ("src/auth",),
        "subject_refs_status": "available",
    }
    defaults.update(overrides)
    return CoordinationSignal(**defaults)  # type: ignore[arg-type]


class TestDetectContradictions:
    def test_overlapping_titles_flagged(self) -> None:
        existing = [
            make_entry(entry_id="pool-entry-1", title="postgres pool capped at 20 connections"),
        ]
        new_title = "postgres pool capped at 30 connections"
        conflicts = detect_contradictions(new_title, existing)
        assert len(conflicts) == 1
        assert conflicts[0].frontmatter.id == "pool-entry-1"

    def test_different_titles_not_flagged(self) -> None:
        existing = [
            make_entry(entry_id="pool-entry-1", title="postgres pool capped at 20"),
        ]
        conflicts = detect_contradictions("redis cache TTL set to 30s", existing)
        assert len(conflicts) == 0

    def test_same_type_directory_only(self) -> None:
        existing = [
            make_entry(
                entry_id="pool-decision-1",
                title="pool limit decision",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
            ),
        ]
        conflicts = detect_contradictions(
            "pool limit project update",
            existing,
            entry_type=EntryType.PROJECT,
        )
        assert len(conflicts) == 0


class TestFindStaleEntries:
    def test_old_entries_flagged(self) -> None:
        old = make_entry(
            entry_id="old",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        stale = find_stale_entries([old], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 1

    def test_recent_entries_not_flagged(self) -> None:
        recent = make_entry(entry_id="recent")
        stale = find_stale_entries([recent], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 0

    def test_expired_entries_excluded(self) -> None:
        expired = make_entry(
            entry_id="expired",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.EXPIRED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        stale = find_stale_entries([expired], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 0


class TestSuggestRevalidationFromSignals:
    def test_merged_signal_matching_metadata_suggests_revalidation(self) -> None:
        entry = make_entry(
            entry_id="auth-token-decision",
            title="Auth token rotation decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW - timedelta(days=10),
            projects=["auth"],
            tags=["tokens"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [_signal()],
            now=BASE_NOW,
        )

        assert len(advisories) == 1
        assert advisories[0].entry_id == "auth-token-decision"
        assert advisories[0].suggested_action == "revalidate"
        assert advisories[0].artifact_ref == "https://github.com/org/api/pull/12"
        assert advisories[0].changed_paths == ("src/auth/tokens.py",)
        assert advisories[0].matched_terms == ("auth", "tokens")

    def test_open_signal_is_not_a_curation_advisory(self) -> None:
        entry = make_entry(
            entry_id="auth-token-decision",
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW - timedelta(days=10),
            projects=["auth"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [_signal(state="open", resolved_at=None)],
            now=BASE_NOW,
        )

        assert advisories == []

    def test_control_label_is_not_enough_to_match(self) -> None:
        entry = make_entry(
            entry_id="ambara-project-entry",
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW - timedelta(days=10),
            tags=["ambara"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [_signal(labels=("ambara",), subject_refs=("src/auth/tokens.py",))],
            now=BASE_NOW,
        )

        assert advisories == []

    def test_resolved_signal_matching_metadata_suggests_revalidation(self) -> None:
        entry = make_entry(
            entry_id="auth-runbook",
            title="Auth runbook",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW - timedelta(days=10),
            projects=["auth"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [
                _signal(
                    signal_id="jira:PROJ:issue:PROJ-123",
                    provider="jira",
                    source="PROJ",
                    artifact_ref="https://jira.example.com/browse/PROJ-123",
                    title="Finish auth rotation",
                    state="resolved",
                    subject_refs=(),
                    subject_areas=("auth",),
                )
            ],
            now=BASE_NOW,
        )

        assert [item.entry_id for item in advisories] == ["auth-runbook"]

    def test_proposed_entries_are_not_revalidation_candidates(self) -> None:
        entry = make_entry(
            entry_id="proposed-auth-decision",
            status=EntryStatus.PROPOSED,
            updated_at=BASE_NOW - timedelta(days=10),
            projects=["auth"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [_signal()],
            now=BASE_NOW,
        )

        assert advisories == []

    def test_low_value_path_terms_are_not_enough_to_match(self) -> None:
        entry = make_entry(
            entry_id="api-style-guide",
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW - timedelta(days=10),
            tags=["api"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [
                _signal(
                    labels=("ambara",),
                    subject_refs=("src/api/views.py",),
                    subject_areas=("src/api",),
                )
            ],
            now=BASE_NOW,
        )

        assert advisories == []

    def test_entry_updated_after_merge_is_not_suggested(self) -> None:
        entry = make_entry(
            entry_id="auth-token-decision",
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW,
            projects=["auth"],
        )

        advisories = suggest_revalidation_from_signals(
            [entry],
            [_signal()],
            now=BASE_NOW,
        )

        assert advisories == []

    def test_active_and_superseded_entries_are_not_suggested(self) -> None:
        active = make_entry(
            entry_id="active-handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            updated_at=BASE_NOW - timedelta(days=10),
            expires_at=BASE_NOW + timedelta(hours=1),
            projects=["auth"],
        )
        superseded = make_entry(
            entry_id="old-auth-decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.SUPERSEDED,
            updated_at=BASE_NOW - timedelta(days=10),
            projects=["auth"],
        )

        advisories = suggest_revalidation_from_signals(
            [active, superseded],
            [_signal()],
            now=BASE_NOW,
        )

        assert advisories == []
