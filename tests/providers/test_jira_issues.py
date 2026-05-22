"""Tests for Jira signal provider."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from jurati.git.config import PRSignalsConfig
from jurati.providers.jira_issues import (
    _build_auth_headers,
    _build_jql,
    _map_status,
    _normalize_issue,
    _sanitize_error,
    fetch_all_signals,
)

NOW = datetime(2026, 5, 21, 14, 0, tzinfo=UTC)


def _issue(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "key": "PROJ-123",
        "fields": {
            "summary": "Auth migration blocks frontend rollout",
            "status": {"name": "In Progress"},
            "labels": ["jurati"],
            "components": [{"name": "auth"}, {"name": "frontend"}],
            "assignee": {"displayName": "Alice", "name": "alice"},
            "reporter": {"displayName": "Bob", "name": "bob"},
            "description": "The auth migration must complete before frontend work.",
            "created": "2026-05-19T10:00:00+00:00",
            "updated": "2026-05-21T12:00:00+00:00",
            "resolutiondate": None,
        },
    }
    if "fields" in overrides:
        fields = dict(base["fields"])
        fields.update(overrides.pop("fields"))
        base["fields"] = fields
    base.update(overrides)
    return base


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("To Do", "open"),
            ("In Progress", "open"),
            ("In Review", "open"),
            ("Done", "resolved"),
            ("Closed", "closed"),
            ("Resolved", "resolved"),
            ("Won't Do", "closed"),
            ("Cancelled", "closed"),
            ("Custom Status", "open"),
        ],
    )
    def test_maps_status(self, raw: str, expected: str) -> None:
        assert _map_status(raw) == expected


class TestNormalizeIssue:
    def test_basic_normalization(self) -> None:
        signal = _normalize_issue(
            _issue(), base_url="https://jira.example.com", include_body_excerpt=True
        )
        assert signal.signal_id == "jira:PROJ:issue:PROJ-123"
        assert signal.provider == "jira"
        assert signal.source == "PROJ"
        assert signal.artifact_ref == "https://jira.example.com/browse/PROJ-123"
        assert signal.title == "Auth migration blocks frontend rollout"
        assert signal.state == "open"
        assert signal.actor == "Alice"
        assert signal.labels == ("jurati",)
        assert signal.subject_areas == ("auth", "frontend")
        assert signal.subject_refs == ()
        assert signal.subject_refs_status == "disabled"

    def test_excerpt_included(self) -> None:
        signal = _normalize_issue(
            _issue(), base_url="https://jira.example.com", include_body_excerpt=True
        )
        assert signal.excerpt == "The auth migration must complete before frontend work."

    def test_excerpt_excluded(self) -> None:
        signal = _normalize_issue(
            _issue(), base_url="https://jira.example.com", include_body_excerpt=False
        )
        assert signal.excerpt is None

    def test_resolved_issue(self) -> None:
        signal = _normalize_issue(
            _issue(
                fields={
                    "status": {"name": "Done"},
                    "resolutiondate": "2026-05-20T15:00:00+00:00",
                }
            ),
            base_url="https://jira.example.com",
            include_body_excerpt=True,
        )
        assert signal.state == "resolved"
        assert signal.resolved_at is not None

    def test_fallback_to_reporter_when_no_assignee(self) -> None:
        signal = _normalize_issue(
            _issue(fields={"assignee": None}),
            base_url="https://jira.example.com",
            include_body_excerpt=True,
        )
        assert signal.actor == "Bob"

    def test_unknown_actor_when_neither(self) -> None:
        signal = _normalize_issue(
            _issue(fields={"assignee": None, "reporter": None}),
            base_url="https://jira.example.com",
            include_body_excerpt=True,
        )
        assert signal.actor == "unknown"

    def test_trailing_slash_in_base_url(self) -> None:
        signal = _normalize_issue(
            _issue(), base_url="https://jira.example.com/", include_body_excerpt=True
        )
        assert signal.artifact_ref == "https://jira.example.com/browse/PROJ-123"


class TestBuildJql:
    def test_basic_jql(self) -> None:
        config = PRSignalsConfig(jira_projects=("PROJ", "WEB"), label="jurati", recency_days=30)
        jql = _build_jql(config)
        assert "project in (PROJ, WEB)" in jql
        assert 'labels = "jurati"' in jql
        assert 'updated >= "-30d"' in jql


class TestBuildAuthHeaders:
    def test_bearer_token(self) -> None:
        with patch.dict("os.environ", {"JIRA_API_TOKEN": "tok123"}, clear=True):
            headers = _build_auth_headers(None)
        assert headers["Authorization"] == "Bearer tok123"

    def test_basic_auth(self) -> None:
        with patch.dict(
            "os.environ",
            {"JIRA_API_TOKEN": "tok123", "JIRA_USER": "alice"},
            clear=True,
        ):
            headers = _build_auth_headers(None)
        assert headers["Authorization"].startswith("Basic ")

    def test_explicit_token_overrides_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            headers = _build_auth_headers("explicit-token")
        assert headers["Authorization"] == "Bearer explicit-token"

    def test_no_auth_returns_empty(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            headers = _build_auth_headers(None)
        assert headers == {}


class TestSanitizeError:
    def test_redacts_long_tokens(self) -> None:
        msg = "Error with token AAAAAAAAAAAAAAAAAAAAAAAAA in request"
        assert "[REDACTED]" in _sanitize_error(msg)

    def test_passes_through_short_strings(self) -> None:
        msg = "Connection refused"
        assert _sanitize_error(msg) == msg


def _mock_fetch(
    config: PRSignalsConfig,
    handler: httpx._transports.mock.MockTransport,
) -> list:
    original_client = httpx.Client

    def patched_client(**kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = handler
        return original_client(**kwargs)

    with (
        patch("jurati.providers.jira_issues.httpx.Client", side_effect=patched_client),
        patch.dict("os.environ", {"JIRA_API_TOKEN": "tok123"}, clear=True),
    ):
        return list(fetch_all_signals(config))


class TestFetchAllSignals:
    def _config(self) -> PRSignalsConfig:
        return PRSignalsConfig(
            provider="jira",
            jira_base_url="https://jira.example.com",
            jira_projects=("PROJ",),
            label="jurati",
        )

    def test_returns_empty_without_base_url(self) -> None:
        config = PRSignalsConfig(provider="jira", jira_projects=("PROJ",))
        assert fetch_all_signals(config, token="tok") == []

    def test_returns_empty_without_projects(self) -> None:
        config = PRSignalsConfig(provider="jira", jira_base_url="https://jira.example.com")
        assert fetch_all_signals(config, token="tok") == []

    def test_returns_empty_without_auth(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert fetch_all_signals(self._config()) == []

    def test_successful_fetch(self) -> None:
        response_data = {
            "issues": [
                _issue(),
                _issue(key="PROJ-456", fields={"summary": "Another issue"}),
            ]
        }
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=response_data))

        signals = _mock_fetch(self._config(), transport)

        assert len(signals) == 2
        assert signals[0].signal_id == "jira:PROJ:issue:PROJ-123"
        assert signals[1].signal_id == "jira:PROJ:issue:PROJ-456"

    def test_handles_api_error(self) -> None:
        transport = httpx.MockTransport(
            lambda req: httpx.Response(500, text="Internal Server Error")
        )

        with patch("jurati.providers.jira_issues.time.sleep"):
            signals = _mock_fetch(self._config(), transport)

        assert signals == []

    def test_handles_auth_failure(self) -> None:
        transport = httpx.MockTransport(lambda req: httpx.Response(401, text="Unauthorized"))

        signals = _mock_fetch(self._config(), transport)
        assert signals == []
