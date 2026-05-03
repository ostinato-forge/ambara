"""Tests for jurati.git.pr."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from jurati.git.pr import create_lightweight_pr, create_pr, create_review_pr


def _mock_gh_run(url: str = "https://github.com/org/repo/pull/42"):
    """Return a mock for subprocess.run that returns the given URL."""
    from unittest.mock import MagicMock

    result = MagicMock()
    result.stdout = f"{url}\n"
    result.returncode = 0
    return result


class TestCreatePR:
    @patch("jurati.git.pr.subprocess.run")
    def test_creates_pr_and_parses_url(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value = _mock_gh_run()
        result = create_pr("/repo", "feat/test", "Test PR", "Body text")

        assert result.url == "https://github.com/org/repo/pull/42"
        assert result.number == 42
        assert result.branch == "feat/test"

    @patch("jurati.git.pr.subprocess.run")
    def test_passes_correct_args(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value = _mock_gh_run()
        create_pr("/repo", "feat/test", "Title", "Body", labels=["a", "b"])

        args = mock_run.call_args
        cmd = args[0][0]
        assert "gh" in cmd
        assert "--title" in cmd
        assert "--label" in cmd

    @patch("jurati.git.pr.subprocess.run")
    def test_error_propagates(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="auth error")
        with pytest.raises(subprocess.CalledProcessError):
            create_pr("/repo", "feat/test", "Title", "Body")


class TestLightweightPR:
    @patch("jurati.git.pr.subprocess.run")
    def test_includes_low_ceremony_label(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value = _mock_gh_run()
        result = create_lightweight_pr("/repo", "feat/proj", "Project PR", "Body")

        cmd = mock_run.call_args[0][0]
        assert "low-ceremony" in cmd
        assert "jurati" in cmd
        assert result.number == 42


class TestReviewPR:
    @patch("jurati.git.pr.subprocess.run")
    def test_includes_review_label(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value = _mock_gh_run()
        result = create_review_pr("/repo", "feat/decision", "Decision PR", "Body")

        cmd = mock_run.call_args[0][0]
        assert "review-required" in cmd
        assert "jurati" in cmd
        assert result.number == 42

    @patch("jurati.git.pr.subprocess.run")
    def test_custom_base_branch(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.return_value = _mock_gh_run()
        create_review_pr("/repo", "feat/x", "Title", "Body", base="develop")

        cmd = mock_run.call_args[0][0]
        base_idx = cmd.index("--base")
        assert cmd[base_idx + 1] == "develop"
