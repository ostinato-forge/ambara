"""Tests for jurati action capture — batching, merge strategies, auto-merge."""

from __future__ import annotations

from jurati.action.capture import (
    collect_jurati_messages,
    derive_batch_branch,
    extract_jurati_lines_from_body,
    message_dedup_key,
)


class TestCollectMessages:
    def test_filters_jurati_commits(self) -> None:
        commits = [
            {"sha": "a1", "message": "jurati: pool limit", "author": "dev@co.com"},
            {"sha": "a2", "message": "feat: other work", "author": "dev@co.com"},
            {"sha": "a3", "message": "jurati(decision): switch to gRPC", "author": "dev@co.com"},
        ]
        results = collect_jurati_messages(commits)
        assert len(results) == 2
        assert results[0]["sha"] == "a1"
        assert results[1]["sha"] == "a3"


class TestBatchBranch:
    def test_batch_branch_name(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456")
        assert branch == "jurati/api-service/batch-abc123"

    def test_single_entry_uses_normal_branch(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456", count=1)
        assert branch is None


class TestSquashMergeSupport:
    def test_extracts_jurati_lines_from_pr_body(self) -> None:
        body = (
            "## Summary\n\n"
            "jurati: pool limit changed\n"
            "jurati(decision): switch to gRPC\n"
            "Other text.\n"
        )
        lines = extract_jurati_lines_from_body(body)
        assert len(lines) == 2
        assert lines[0] == "jurati: pool limit changed"
        assert lines[1] == "jurati(decision): switch to gRPC"

    def test_empty_body_returns_empty(self) -> None:
        assert extract_jurati_lines_from_body("") == []
        assert extract_jurati_lines_from_body(None) == []


class TestMessageDedupKey:
    def test_deterministic(self) -> None:
        k1 = message_dedup_key("jurati: pool limit")
        k2 = message_dedup_key("jurati: pool limit")
        assert k1 == k2

    def test_different_messages_different_keys(self) -> None:
        k1 = message_dedup_key("jurati: pool limit")
        k2 = message_dedup_key("jurati: cache TTL")
        assert k1 != k2
