"""Tests for ambara.capture.pending — offline capture queue."""

from __future__ import annotations

from pathlib import Path

from ambara.capture.pending import (
    list_pending,
    remove_pending,
    save_pending,
)

SHA_A = "abc123def456abc123def456abc123def456abc1"
SHA_B = "bbb222ccc333ddd444eee555fff666aaa777bbb8"
SHA_C = "ccc333ddd444eee555fff666aaa777bbb8ccc333"


class TestPendingQueue:
    def test_save_and_list(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(
            str(git_dir),
            SHA_A,
            "ambara: pool limit",
            author="dev@co.com",
            repo_slug="api-service",
        )
        pending = list_pending(str(git_dir))
        assert len(pending) == 1
        assert pending[0]["commit_sha"] == SHA_A
        assert pending[0]["message"] == "ambara: pool limit"
        assert pending[0]["author"] == "dev@co.com"
        assert pending[0]["repo_slug"] == "api-service"

    def test_remove_clears_marker(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), SHA_A, "ambara: pool limit")
        remove_pending(str(git_dir), SHA_A)
        assert list_pending(str(git_dir)) == []

    def test_list_empty_dir(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert list_pending(str(git_dir)) == []

    def test_multiple_pending(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), SHA_B, "ambara: first")
        save_pending(str(git_dir), SHA_C, "ambara: second")
        pending = list_pending(str(git_dir))
        assert len(pending) == 2
