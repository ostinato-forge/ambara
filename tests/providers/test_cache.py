"""Tests for PR signal cache."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ambara.core.pr_signals import PRSignal
from ambara.providers.cache import SignalCache

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _signal(number: int = 42, updated_at: datetime | None = None) -> PRSignal:
    return PRSignal(
        signal_id=f"github:org/api:pull:{number}",
        provider="github",
        repo="org/api",
        number=number,
        url=f"https://github.com/org/api/pull/{number}",
        title=f"PR #{number}",
        body_excerpt=None,
        author="tony",
        state="open",
        labels=("ambara",),
        created_at=NOW - timedelta(days=2),
        updated_at=updated_at or NOW - timedelta(hours=6),
        merged_at=None,
        changed_paths=(),
        target_areas=(),
    )


class TestSignalCache:
    def test_empty_cache(self) -> None:
        cache = SignalCache()
        assert cache.size == 0
        assert cache.get_signals() == []

    def test_update_populates_cache(self) -> None:
        cache = SignalCache()
        cache.update([_signal(1), _signal(2)], now=NOW)
        assert cache.size == 2

    def test_update_replaces_previous(self) -> None:
        cache = SignalCache()
        cache.update([_signal(1), _signal(2)], now=NOW)
        cache.update([_signal(3)], now=NOW)
        assert cache.size == 1
        assert cache.get_signals()[0].number == 3

    def test_stale_signals_filtered_on_update(self) -> None:
        cache = SignalCache(recency_days=7)
        old = _signal(1, updated_at=NOW - timedelta(days=30))
        fresh = _signal(2, updated_at=NOW - timedelta(hours=1))
        cache.update([old, fresh], now=NOW)
        assert cache.size == 1
        assert cache.get_signals()[0].number == 2

    def test_drop_signal(self) -> None:
        cache = SignalCache()
        cache.update([_signal(1), _signal(2)], now=NOW)
        cache.drop_signal("github:org/api:pull:1")
        assert cache.size == 1

    def test_drop_nonexistent_is_safe(self) -> None:
        cache = SignalCache()
        cache.drop_signal("nonexistent")
        assert cache.size == 0

    def test_evict_stale(self) -> None:
        cache = SignalCache(recency_days=7)
        old_signals = [
            _signal(1, updated_at=NOW - timedelta(days=10)),
            _signal(2, updated_at=NOW - timedelta(days=10)),
        ]
        cache.update(old_signals, now=NOW - timedelta(days=10))
        assert cache.size == 2
        evicted = cache.evict_stale(now=NOW)
        assert evicted == 2
        assert cache.size == 0

    def test_needs_refresh_initially(self) -> None:
        cache = SignalCache()
        assert cache.needs_refresh(now=NOW)

    def test_needs_refresh_after_interval(self) -> None:
        cache = SignalCache(refresh_interval=300)
        cache.update([], now=NOW)
        assert not cache.needs_refresh(now=NOW + timedelta(seconds=100))
        assert cache.needs_refresh(now=NOW + timedelta(seconds=301))

    def test_last_refresh_tracks(self) -> None:
        cache = SignalCache()
        assert cache.last_refresh is None
        cache.update([], now=NOW)
        assert cache.last_refresh == NOW

    def test_get_signals_returns_copy(self) -> None:
        cache = SignalCache()
        cache.update([_signal(1)], now=NOW)
        signals = cache.get_signals()
        signals.clear()
        assert cache.size == 1
