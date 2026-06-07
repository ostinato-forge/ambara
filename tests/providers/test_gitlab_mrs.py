# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for GitLab merge request adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError
from ambara.providers.gitlab_mrs import fetch_all_signals, fetch_labeled_merge_requests


def _config() -> PRSignalsConfig:
    return PRSignalsConfig(
        provider="gitlab",
        repos=("group/api",),
        label="ambara",
        gitlab_base_url="https://gitlab.example.com",
    )


class TestFetchLabeledMergeRequests:
    @patch("ambara.providers.gitlab_mrs.read_token", return_value="tok_abc")
    @patch("ambara.providers.gitlab_mrs.httpx.get")
    def test_fetches_gitlab_merge_requests(self, mock_get: MagicMock, _tok: MagicMock) -> None:
        list_response = MagicMock()
        list_response.status_code = 200
        list_response.json.return_value = [{"iid": 42}]

        detail_response = MagicMock()
        detail_response.status_code = 200
        detail_response.json.return_value = {
            "iid": 42,
            "web_url": "https://gitlab.example.com/group/api/-/merge_requests/42",
            "title": "Coordinate auth migration",
            "description": "This merge request changes the auth contract.",
            "author": {"username": "alice"},
            "state": "opened",
            "labels": ["ambara"],
            "created_at": "2026-06-01T12:00:00Z",
            "updated_at": "2026-06-02T12:00:00Z",
            "merged_at": None,
        }

        changes_response = MagicMock()
        changes_response.status_code = 200
        changes_response.json.return_value = {
            "changes": [{"new_path": "src/auth/token.py"}],
        }

        mock_get.side_effect = [list_response, detail_response, changes_response]

        signals = fetch_labeled_merge_requests(_config(), "group/api")

        assert len(signals) == 1
        assert signals[0].provider == "gitlab"
        assert signals[0].signal_id == "gitlab:group/api:merge_request:42"
        assert signals[0].url == "https://gitlab.example.com/group/api/-/merge_requests/42"
        assert signals[0].changed_paths == ("src/auth/token.py",)
        assert signals[0].target_areas == ("src/auth",)

    @patch("ambara.providers.gitlab_mrs.read_token", return_value=None)
    def test_missing_token_raises(self, _tok: MagicMock) -> None:
        with pytest.raises(SignalProviderError, match="GitLab merge request search failed"):
            fetch_labeled_merge_requests(_config(), "group/api")

    @patch("ambara.providers.gitlab_mrs.read_token", return_value="tok_abc")
    @patch("ambara.providers.gitlab_mrs.httpx.get")
    def test_non_200_list_raises(self, mock_get: MagicMock, _tok: MagicMock) -> None:
        list_response = MagicMock()
        list_response.status_code = 500
        list_response.json.return_value = {}
        mock_get.return_value = list_response

        with pytest.raises(SignalProviderError, match="GitLab merge request search failed"):
            fetch_labeled_merge_requests(_config(), "group/api")


class TestFetchAllSignals:
    @patch("ambara.providers.gitlab_mrs.fetch_labeled_merge_requests")
    def test_fetch_all_signals(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = []
        assert fetch_all_signals(_config()) == []
        mock_fetch.assert_called_once_with(_config(), "group/api", token=None)
