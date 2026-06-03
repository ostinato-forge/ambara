"""Tests for GitHub PR adapter."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError
from ambara.providers.github_prs import (
    _derive_target_areas,
    _is_rate_limit_error,
    _normalize_pr,
    _run_gh_api_json,
    _sanitize_error,
    fetch_all_signals,
    fetch_labeled_prs,
)

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _raw_pr(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "number": 42,
        "title": "Fix auth token refresh",
        "body": "This resolves the token refresh race condition.",
        "state": "open",
        "html_url": "https://github.com/org/api/pull/42",
        "user": {"login": "tony"},
        "labels": [{"name": "ambara"}],
        "created_at": "2026-05-02T12:00:00Z",
        "updated_at": "2026-05-04T06:00:00Z",
        "merged_at": None,
        "files": [
            {"filename": "src/auth/token.py"},
            {"filename": "src/auth/refresh.py"},
        ],
    }
    defaults.update(overrides)
    return defaults


class TestSanitizeError:
    def test_redacts_classic_token(self) -> None:
        msg = "auth failed: ghp_abcdefghijklmnopqrstuvwxyz123456"
        sanitized = _sanitize_error(msg)
        assert "ghp_" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_redacts_fine_grained_token(self) -> None:
        msg = "error: github_pat_abcdefghijklmnopqrstuvwx"
        sanitized = _sanitize_error(msg)
        assert "github_pat_" not in sanitized

    def test_preserves_non_token_text(self) -> None:
        msg = "connection refused"
        assert _sanitize_error(msg) == msg


class TestDeriveTargetAreas:
    def test_extracts_top_two_levels(self) -> None:
        paths = ["src/auth/token.py", "src/auth/refresh.py", "tests/auth/test_token.py"]
        areas = _derive_target_areas(paths)
        assert "src/auth" in areas
        assert "tests/auth" in areas

    def test_single_component_path_excluded(self) -> None:
        areas = _derive_target_areas(["README.md"])
        assert areas == ()


class TestNormalizePR:
    def test_basic_normalization(self) -> None:
        raw = _raw_pr()
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=True, include_changed_paths=True)
        assert sig.signal_id == "github:org/api:pull:42"
        assert sig.provider == "github"
        assert sig.repo == "org/api"
        assert sig.number == 42
        assert sig.author == "tony"
        assert sig.state == "open"
        assert "ambara" in sig.labels
        assert len(sig.changed_paths) == 2
        assert sig.changed_paths_status == "available"

    def test_merged_state_from_merged_at(self) -> None:
        raw = _raw_pr(state="closed", merged_at="2026-05-03T10:00:00Z")
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=True, include_changed_paths=True)
        assert sig.state == "merged"
        assert sig.merged_at is not None

    def test_body_excerpt_truncation(self) -> None:
        raw = _raw_pr(body="x" * 1000)
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=True, include_changed_paths=True)
        assert sig.body_excerpt is not None
        assert len(sig.body_excerpt) <= 500

    def test_body_excerpt_disabled(self) -> None:
        raw = _raw_pr()
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=False, include_changed_paths=True)
        assert sig.body_excerpt is None

    def test_changed_paths_disabled(self) -> None:
        raw = _raw_pr()
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=True, include_changed_paths=False)
        assert sig.changed_paths == ()
        assert sig.changed_paths_status == "disabled"

    def test_missing_changed_paths_marked_unavailable(self) -> None:
        raw = _raw_pr()
        raw.pop("files")
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=True, include_changed_paths=True)
        assert sig.changed_paths == ()
        assert sig.changed_paths_status == "unavailable"

    def test_target_areas_derived(self) -> None:
        raw = _raw_pr()
        sig = _normalize_pr(raw, "org/api", include_body_excerpt=True, include_changed_paths=True)
        assert "src/auth" in sig.target_areas


class TestFetchLabeledPRs:
    def test_repo_not_configured_returns_empty(self) -> None:
        config = PRSignalsConfig(repos=("org/web",))
        result = fetch_labeled_prs(config, "org/api")
        assert result == []

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_successful_fetch(self, mock_run: Any) -> None:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps([_raw_pr()]),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(_raw_pr()),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(_raw_pr()["files"]),
                stderr="",
            ),
        ]
        config = PRSignalsConfig(repos=("org/api",))
        result = fetch_labeled_prs(config, "org/api")
        assert len(result) == 1
        assert result[0].number == 42
        assert result[0].changed_paths == ("src/auth/token.py", "src/auth/refresh.py")
        assert result[0].changed_paths_status == "available"
        assert mock_run.call_count == 3
        search_cmd = mock_run.call_args_list[0].args[0]
        assert any("label:ambara" in arg for arg in search_cmd)

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_api_error_raises_provider_error(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="401 Unauthorized",
        )
        config = PRSignalsConfig(repos=("org/api",))
        with pytest.raises(SignalProviderError, match="GitHub search failed"):
            fetch_labeled_prs(config, "org/api")

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_timeout_raises_provider_error(self, mock_run: Any) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)
        config = PRSignalsConfig(repos=("org/api",))
        with pytest.raises(SignalProviderError, match="GitHub search failed"):
            fetch_labeled_prs(config, "org/api")

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_invalid_json_raises_provider_error(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="not json",
            stderr="",
        )
        config = PRSignalsConfig(repos=("org/api",))
        with pytest.raises(SignalProviderError, match="GitHub search failed"):
            fetch_labeled_prs(config, "org/api")

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_gh_not_available_raises_provider_error(self, mock_run: Any) -> None:
        mock_run.side_effect = OSError("gh not found")
        config = PRSignalsConfig(repos=("org/api",))
        with pytest.raises(SignalProviderError, match="GitHub search failed"):
            fetch_labeled_prs(config, "org/api")

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_file_fetch_failure_raises_provider_error(self, mock_run: Any) -> None:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps([_raw_pr()]),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(_raw_pr()),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="boom",
            ),
        ]
        config = PRSignalsConfig(repos=("org/api",))
        with pytest.raises(SignalProviderError, match="GitHub PR file fetch failed"):
            fetch_labeled_prs(config, "org/api")

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_detail_fetch_failure_raises_provider_error(self, mock_run: Any) -> None:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps([_raw_pr(title="Search title")]),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="detail failed",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(_raw_pr()["files"]),
                stderr="",
            ),
        ]
        config = PRSignalsConfig(repos=("org/api",))
        with pytest.raises(SignalProviderError, match="GitHub PR detail fetch failed"):
            fetch_labeled_prs(config, "org/api")

    @patch("ambara.providers.github_prs.subprocess.run")
    def test_token_sanitized_in_error(self, mock_run: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="auth error: ghp_abcdefghijklmnopqrstuvwxyz123456 failed",
        )
        config = PRSignalsConfig(repos=("org/api",))
        import logging

        with patch.object(logging.getLogger("ambara.providers.github_prs"), "warning") as mock_warn:
            with pytest.raises(SignalProviderError):
                fetch_labeled_prs(config, "org/api")
            if mock_warn.called:
                logged = mock_warn.call_args[0][-1]
                assert "ghp_" not in logged


class TestRateLimitDetection:
    def test_detects_rate_limit_phrase(self) -> None:
        assert _is_rate_limit_error("API rate limit exceeded for user")

    def test_detects_429(self) -> None:
        assert _is_rate_limit_error("HTTP 429 Too Many Requests")

    def test_case_insensitive(self) -> None:
        assert _is_rate_limit_error("Rate Limit exceeded")

    def test_non_rate_limit_error(self) -> None:
        assert not _is_rate_limit_error("401 Unauthorized")

    def test_empty_string(self) -> None:
        assert not _is_rate_limit_error("")


class TestRunGhApiJsonRetry:
    @patch("ambara.providers.github_prs.time.sleep")
    @patch("ambara.providers.github_prs.subprocess.run")
    def test_retries_on_rate_limit(self, mock_run: Any, mock_sleep: Any) -> None:
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="API rate limit exceeded"
            ),
            subprocess.CompletedProcess(args=[], returncode=0, stdout='{"ok": true}', stderr=""),
        ]
        result = _run_gh_api_json(
            ["gh", "api", "test"],
            repo="org/repo",
            description="test",
            env={},
            max_retries=2,
        )
        assert result == {"ok": True}
        assert mock_run.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("ambara.providers.github_prs.time.sleep")
    @patch("ambara.providers.github_prs.subprocess.run")
    def test_no_retry_on_auth_error(self, mock_run: Any, mock_sleep: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="401 Unauthorized"
        )
        result = _run_gh_api_json(
            ["gh", "api", "test"],
            repo="org/repo",
            description="test",
            env={},
            max_retries=2,
        )
        assert result is None
        assert mock_run.call_count == 1
        assert mock_sleep.call_count == 0

    @patch("ambara.providers.github_prs.time.sleep")
    @patch("ambara.providers.github_prs.subprocess.run")
    def test_exhausts_retries(self, mock_run: Any, mock_sleep: Any) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="API rate limit exceeded"
        )
        result = _run_gh_api_json(
            ["gh", "api", "test"],
            repo="org/repo",
            description="test",
            env={},
            max_retries=2,
        )
        assert result is None
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2


class TestFetchAllSignals:
    @patch("ambara.providers.github_prs.fetch_labeled_prs")
    def test_fetches_all_repos(self, mock_fetch: Any) -> None:
        mock_fetch.return_value = []
        config = PRSignalsConfig(repos=("org/api", "org/web"))
        fetch_all_signals(config)
        assert mock_fetch.call_count == 2
