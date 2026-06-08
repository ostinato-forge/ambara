# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for fixture-backed PR signal provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError
from ambara.providers.fixture_signals import fetch_fixture_signals
from ambara.providers.signals import fetch_all_signals

NOW = datetime.now(UTC)


def _write_fixture(path: Path, signals: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"signals": signals}) + "\n")


def _signal(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "repo": "org/api",
        "number": 7,
        "url": "https://github.com/org/api/pull/7",
        "title": "Auth contract migration blocks frontend session rollout",
        "body_excerpt": "Downstream web work should wait for this API contract PR.",
        "author": "alice",
        "state": "open",
        "labels": ["ambara"],
        "created_at": (NOW - timedelta(days=1)).isoformat(),
        "updated_at": NOW.isoformat(),
        "changed_paths": ["contracts/auth/session.json"],
    }
    base.update(overrides)
    return base


def _coordination_signal(**overrides: object) -> CoordinationSignal:
    fields: dict[str, object] = {
        "signal_id": "jira:OPS-123",
        "provider": "jira",
        "source": "OPS",
        "artifact_ref": "https://jira.example/browse/OPS-123",
        "title": "Auth migration blocker",
        "excerpt": "Token rollout is blocked on identity review.",
        "actor": "alice",
        "state": "open",
        "labels": ("ambara",),
        "created_at": NOW,
        "updated_at": NOW,
        "resolved_at": None,
        "subject_refs": ("src/auth/tokens.py",),
        "subject_areas": ("src/auth",),
    }
    fields.update(overrides)
    return CoordinationSignal(**fields)  # type: ignore[arg-type]


class TestFixtureSignals:
    def test_loads_configured_labelled_signal(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(fixture, [_signal()])
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_fixture_signals(config)

        assert len(signals) == 1
        assert signals[0].repo == "org/api"
        assert signals[0].number == 7
        assert signals[0].labels == ("ambara",)
        assert signals[0].changed_paths == ("contracts/auth/session.json",)
        assert signals[0].target_areas == ("contracts/auth",)

    def test_loads_gitlab_review_signal(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(
            fixture,
            [
                _signal(
                    provider="gitlab",
                    signal_id="gitlab:org/api:merge_request:7",
                    url="https://gitlab.com/org/api/-/merge_requests/7",
                )
            ],
        )
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_fixture_signals(config)

        assert len(signals) == 1
        assert signals[0].provider == "gitlab"
        assert signals[0].signal_id == "gitlab:org/api:merge_request:7"

    def test_filters_unconfigured_repos_and_labels(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(
            fixture,
            [
                _signal(repo="org/other"),
                _signal(labels=["needs-review"]),
                _signal(number=9),
            ],
        )
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_fixture_signals(config)

        assert [signal.number for signal in signals] == [9]

    def test_filters_stale_signals(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(
            fixture,
            [_signal(updated_at=(NOW - timedelta(days=31)).isoformat())],
        )
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture), recency_days=30)

        assert fetch_fixture_signals(config) == []

    def test_respects_body_and_path_config(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(fixture, [_signal()])
        config = PRSignalsConfig(
            repos=("org/api",),
            fixture_path=str(fixture),
            include_body_excerpt=False,
            include_changed_paths=False,
        )

        signals = fetch_fixture_signals(config)

        assert signals[0].body_excerpt is None
        assert signals[0].changed_paths == ()
        assert signals[0].changed_paths_status == "disabled"

    def test_bad_fixture_raises_provider_error(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        fixture.write_text("{not json")
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        with pytest.raises(SignalProviderError, match="Source fixture unavailable"):
            fetch_fixture_signals(config)

    def test_malformed_fixture_shape_raises_provider_error(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        fixture.write_text(json.dumps({"signals": {"not": "a list"}}))
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        with pytest.raises(SignalProviderError, match="Source fixture must be a list"):
            fetch_fixture_signals(config)


class TestSignalProviderEntrypoint:
    def test_fixture_takes_provider_path(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(fixture, [_signal()])
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_all_signals(config)

        assert len(signals) == 1
        assert signals[0].repo == "org/api"
        assert signals[0].author == "unknown"

    def test_runtime_signal_path_applies_source_safety(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        token = "ghp_" + ("A" * 32)
        _write_fixture(
            fixture,
            [
                _signal(
                    title=f"Rotate token {token}",
                    body_excerpt=f"password={token}",
                    changed_paths=["../secrets.env", "contracts/auth/session.json"],
                )
            ],
        )
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_all_signals(config)

        assert len(signals) == 1
        signal = signals[0]
        assert isinstance(signal, PRSignal)
        assert "[redacted:credential]" in signal.title
        assert "[redacted:credential]" in (signal.body_excerpt or "")
        assert signal.changed_paths == ("contracts/auth/session.json",)
        assert signal.author == "unknown"

    def test_configured_provider_failure_raises(self) -> None:
        config = PRSignalsConfig(repos=("org/api",))

        with (
            patch(
                "ambara.sources.legacy_providers.fetch_github_signals",
                side_effect=SignalProviderError("GitHub search failed"),
            ),
            pytest.raises(SignalProviderError, match="GitHub: source refresh failed"),
        ):
            fetch_all_signals(config)

    def test_partial_provider_failure_returns_successful_results(self) -> None:
        signal = _coordination_signal()
        config = PRSignalsConfig(
            repos=("org/api",),
            jira_base_url="https://jira.example",
            jira_projects=("OPS",),
        )

        with (
            patch(
                "ambara.sources.legacy_providers.fetch_github_signals",
                side_effect=SignalProviderError("GitHub search failed"),
            ),
            patch("ambara.sources.legacy_providers.fetch_jira_signals", return_value=[signal]),
        ):
            signals = fetch_all_signals(config)

        assert len(signals) == 1
        assert signals[0].signal_id == signal.signal_id
        assert signals[0].source == "OPS"
        assert signals[0].actor == "unknown"

    def test_gitlab_provider_path_is_used(self) -> None:
        config = PRSignalsConfig(provider="gitlab", repos=("group/api",))

        with patch(
            "ambara.sources.legacy_providers.fetch_gitlab_signals",
            return_value=[],
        ) as fetch:
            assert fetch_all_signals(config) == []
        fetch.assert_called_once()

    def test_jira_provider_path_is_registry_owned(self) -> None:
        signal = _coordination_signal()
        config = PRSignalsConfig(
            jira_base_url="https://jira.example",
            jira_projects=("OPS",),
        )

        with patch(
            "ambara.sources.legacy_providers.fetch_jira_signals",
            return_value=[signal],
        ) as fetch:
            signals = fetch_all_signals(config)

        assert len(signals) == 1
        assert signals[0].signal_id == signal.signal_id
        assert signals[0].source == "OPS"
        fetch.assert_called_once()

    def test_unknown_provider_errors_cleanly(self) -> None:
        config = PRSignalsConfig(provider="linear", repos=("team/backend",))

        with pytest.raises(SignalProviderError, match="unknown signal provider"):
            fetch_all_signals(config)
