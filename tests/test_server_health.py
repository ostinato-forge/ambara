"""Sync health tracking tests."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.index import Index
from jurati.git.config import JuratiConfig
from jurati.server import ServerState, SyncHealth

NOW = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


def _build_state() -> ServerState:
    return ServerState(
        config=JuratiConfig(remote_url="https://example.com/repo.git"),
        repo_path="/fake/repo",
        index=Index(),
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
    )


class TestSyncHealth:
    def test_initial_state(self) -> None:
        state = _build_state()
        assert state.sync_health.last_success == NOW
        assert state.sync_health.last_failure is None
        assert state.sync_health.last_error is None
        assert state.sync_health.consecutive_failures == 0

    def test_failure_increments_count(self) -> None:
        state = _build_state()
        fail_time = datetime(2026, 5, 2, 13, 0, tzinfo=UTC)
        state.sync_health.last_failure = fail_time
        state.sync_health.last_error = "connection refused"
        state.sync_health.consecutive_failures = 1

        assert state.sync_health.consecutive_failures == 1
        assert state.sync_health.last_error == "connection refused"
        assert state.sync_health.last_success == NOW

    def test_success_resets_failures(self) -> None:
        state = _build_state()
        state.sync_health.consecutive_failures = 3
        state.sync_health.last_error = "timeout"

        success_time = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        state.sync_health.last_success = success_time
        state.sync_health.consecutive_failures = 0
        state.sync_health.last_error = None

        assert state.sync_health.consecutive_failures == 0
        assert state.sync_health.last_error is None
        assert state.sync_health.last_success == success_time

    def test_failure_preserves_last_good_index(self) -> None:
        state = _build_state()
        original_index = state.index

        state.sync_health.last_failure = datetime(2026, 5, 2, 13, 0, tzinfo=UTC)
        state.sync_health.last_error = "network error"
        state.sync_health.consecutive_failures = 1

        assert state.index is original_index

    def test_multiple_failures_tracked(self) -> None:
        state = _build_state()
        for i in range(1, 4):
            state.sync_health.consecutive_failures = i
            state.sync_health.last_error = f"error {i}"

        assert state.sync_health.consecutive_failures == 3
        assert state.sync_health.last_error == "error 3"
