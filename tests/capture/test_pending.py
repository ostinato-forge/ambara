"""Tests for jurati.capture.pending — offline capture queue."""

from __future__ import annotations

from pathlib import Path

from jurati.capture.pending import (
    list_pending,
    remove_pending,
    save_pending,
)


class TestPendingQueue:
    def test_save_and_list(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), "abc123", "jurati: pool limit")
        pending = list_pending(str(git_dir))
        assert len(pending) == 1
        assert pending[0]["commit_sha"] == "abc123"
        assert pending[0]["message"] == "jurati: pool limit"

    def test_remove_clears_marker(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), "abc123", "jurati: pool limit")
        remove_pending(str(git_dir), "abc123")
        assert list_pending(str(git_dir)) == []

    def test_list_empty_dir(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert list_pending(str(git_dir)) == []

    def test_multiple_pending(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        save_pending(str(git_dir), "aaa111", "jurati: first")
        save_pending(str(git_dir), "bbb222", "jurati: second")
        pending = list_pending(str(git_dir))
        assert len(pending) == 2
