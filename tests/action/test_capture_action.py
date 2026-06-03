"""Tests for ambara action capture — batching, merge strategies, auto-merge."""

from __future__ import annotations

from ambara.action.capture import (
    collect_ambara_messages,
    derive_batch_branch,
    extract_ambara_lines_from_body,
    message_dedup_key,
)


class TestCollectMessages:
    def test_filters_ambara_commits(self) -> None:
        commits = [
            {"sha": "a1", "message": "ambara: pool limit", "author": "dev@co.com"},
            {"sha": "a2", "message": "feat: other work", "author": "dev@co.com"},
            {"sha": "a3", "message": "ambara(decision): switch to gRPC", "author": "dev@co.com"},
        ]
        results = collect_ambara_messages(commits)
        assert len(results) == 2
        assert results[0]["sha"] == "a1"
        assert results[1]["sha"] == "a3"


class TestBatchBranch:
    def test_batch_branch_name(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456")
        assert branch == "ambara/api-service/batch-abc123"

    def test_single_entry_uses_normal_branch(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456", count=1)
        assert branch is None


class TestSquashMergeSupport:
    def test_extracts_ambara_lines_from_pr_body(self) -> None:
        body = (
            "## Summary\n\n"
            "ambara: pool limit changed\n"
            "ambara(decision): switch to gRPC\n"
            "Other text.\n"
        )
        lines = extract_ambara_lines_from_body(body)
        assert len(lines) == 2
        assert lines[0] == "ambara: pool limit changed"
        assert lines[1] == "ambara(decision): switch to gRPC"

    def test_empty_body_returns_empty(self) -> None:
        assert extract_ambara_lines_from_body("") == []
        assert extract_ambara_lines_from_body(None) == []


class TestMessageDedupKey:
    def test_deterministic(self) -> None:
        k1 = message_dedup_key("ambara: pool limit")
        k2 = message_dedup_key("ambara: pool limit")
        assert k1 == k2

    def test_different_messages_different_keys(self) -> None:
        k1 = message_dedup_key("ambara: pool limit")
        k2 = message_dedup_key("ambara: cache TTL")
        assert k1 != k2
