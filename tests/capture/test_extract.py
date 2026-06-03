# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.capture.extract."""

from __future__ import annotations

from ambara.capture.extract import (
    derive_entry_id,
    parse_commit_message,
    scan_secrets,
)
from ambara.core.schema import EntryType, EscalationLevel


class TestParseCommitMessage:
    def test_bare_ambara_prefix(self) -> None:
        result = parse_commit_message("ambara: postgres pool at 20 max")
        assert result is not None
        assert result.title == "postgres pool at 20 max"
        assert result.tag is None
        assert result.entry_type == EntryType.PROJECT
        assert result.level == EscalationLevel.L1
        assert result.body == ""

    def test_decision_tag(self) -> None:
        result = parse_commit_message("ambara(decision): switch to gRPC")
        assert result is not None
        assert result.title == "switch to gRPC"
        assert result.tag == "decision"
        assert result.entry_type == EntryType.DECISION
        assert result.level == EscalationLevel.L2

    def test_principle_tag(self) -> None:
        result = parse_commit_message("ambara(principle): all calls go through gateway")
        assert result is not None
        assert result.entry_type == EntryType.PRINCIPLE
        assert result.level == EscalationLevel.L3

    def test_workflow_tag(self) -> None:
        result = parse_commit_message("ambara(workflow): PRs require two approvals")
        assert result is not None
        assert result.entry_type == EntryType.WORKFLOW
        assert result.level == EscalationLevel.L2

    def test_unknown_tag_defaults_to_project(self) -> None:
        result = parse_commit_message("ambara(foobar): some note")
        assert result is not None
        assert result.entry_type == EntryType.PROJECT
        assert result.level == EscalationLevel.L1

    def test_multiline_body(self) -> None:
        msg = "ambara: pool limit changed\n\nWe hit OOM on staging with 50 connections."
        result = parse_commit_message(msg)
        assert result is not None
        assert result.title == "pool limit changed"
        assert result.body == "We hit OOM on staging with 50 connections."

    def test_no_prefix_returns_none(self) -> None:
        assert parse_commit_message("feat: add new feature") is None

    def test_empty_title_returns_none(self) -> None:
        assert parse_commit_message("ambara: ") is None
        assert parse_commit_message("ambara:") is None

    def test_whitespace_stripping(self) -> None:
        result = parse_commit_message("ambara:   spaced title  ")
        assert result is not None
        assert result.title == "spaced title"


class TestDeriveEntryId:
    def test_basic_id(self) -> None:
        entry_id = derive_entry_id("api-service", "postgres pool at 20 max")
        assert entry_id == "api-service-postgres-pool-at-20-max"

    def test_special_chars_slugified(self) -> None:
        entry_id = derive_entry_id("frontend", "switch to gRPC — faster!")
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in entry_id)

    def test_truncation_at_120_chars(self) -> None:
        long_title = "a " * 100
        entry_id = derive_entry_id("repo", long_title)
        assert len(entry_id) <= 120

    def test_collision_suffix(self) -> None:
        base_id = derive_entry_id("repo", "title")
        suffixed_id = derive_entry_id("repo", "title", commit_sha="abc123", collision=True)
        assert suffixed_id.startswith(base_id)
        assert len(suffixed_id) > len(base_id)

    def test_collision_suffix_strips_trailing_hyphen_after_truncation(self) -> None:
        entry_id = derive_entry_id("repo", "a " * 100, commit_sha="abc123", collision=True)
        assert len(entry_id) <= 120
        assert "--" not in entry_id

    def test_deterministic(self) -> None:
        id1 = derive_entry_id("repo", "same title", commit_sha="sha1")
        id2 = derive_entry_id("repo", "same title", commit_sha="sha1")
        assert id1 == id2


class TestScanSecrets:
    def test_api_key_detected(self) -> None:
        assert scan_secrets("new key is sk-abc123def456") is True

    def test_password_detected(self) -> None:
        assert scan_secrets("password=hunter2") is True

    def test_normal_text_passes(self) -> None:
        assert scan_secrets("postgres pool at 20 max") is False

    def test_connection_string_detected(self) -> None:
        assert scan_secrets("postgresql://user:pass@host/db") is True

    def test_token_detected(self) -> None:
        assert scan_secrets("ghp_ABCDEFghijkl1234567890abcdefghij") is True
