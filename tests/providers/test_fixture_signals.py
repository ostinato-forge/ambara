"""Tests for fixture-backed PR signal provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jurati.git.config import PRSignalsConfig
from jurati.providers.fixture_signals import fetch_fixture_signals
from jurati.providers.signals import fetch_all_signals

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
        "labels": ["jurati"],
        "created_at": (NOW - timedelta(days=1)).isoformat(),
        "updated_at": NOW.isoformat(),
        "changed_paths": ["contracts/auth/session.json"],
    }
    base.update(overrides)
    return base


class TestFixtureSignals:
    def test_loads_configured_labelled_signal(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(fixture, [_signal()])
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_fixture_signals(config)

        assert len(signals) == 1
        assert signals[0].repo == "org/api"
        assert signals[0].number == 7
        assert signals[0].labels == ("jurati",)
        assert signals[0].changed_paths == ("contracts/auth/session.json",)
        assert signals[0].target_areas == ("contracts/auth",)

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

    def test_bad_fixture_returns_empty(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        fixture.write_text("{not json")
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        assert fetch_fixture_signals(config) == []


class TestSignalProviderEntrypoint:
    def test_fixture_takes_provider_path(self, tmp_path: Path) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(fixture, [_signal()])
        config = PRSignalsConfig(repos=("org/api",), fixture_path=str(fixture))

        signals = fetch_all_signals(config)

        assert len(signals) == 1
        assert signals[0].repo == "org/api"
