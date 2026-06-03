"""Signal cache with recency expiry.

Stores normalized PRSignal or CoordinationSignal objects to avoid
hitting the provider on every context() call. Thread-safe for
concurrent MCP requests.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from ambara.core.pr_signals import CoordinationSignal, PRSignal

CachedSignal = PRSignal | CoordinationSignal


class SignalCache:
    def __init__(self, *, recency_days: int = 30, refresh_interval: int = 300) -> None:
        self._recency_days = recency_days
        self._refresh_interval = refresh_interval
        self._signals: dict[str, CachedSignal] = {}
        self._last_refresh: datetime | None = None
        self._lock = threading.Lock()

    def get_signals(self) -> list[CachedSignal]:
        with self._lock:
            return list(self._signals.values())

    def needs_refresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        with self._lock:
            if self._last_refresh is None:
                return True
            return (now - self._last_refresh).total_seconds() >= self._refresh_interval

    def update(
        self, signals: list[CachedSignal] | Sequence[CachedSignal], *, now: datetime | None = None
    ) -> None:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self._recency_days)
        with self._lock:
            self._signals.clear()
            for sig in signals:
                if sig.updated_at >= cutoff:
                    self._signals[sig.signal_id] = sig
            self._last_refresh = now

    def drop_signal(self, signal_id: str) -> None:
        with self._lock:
            self._signals.pop(signal_id, None)

    def evict_stale(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self._recency_days)
        evicted = 0
        with self._lock:
            stale = [sid for sid, sig in self._signals.items() if sig.updated_at < cutoff]
            for sid in stale:
                del self._signals[sid]
                evicted += 1
        return evicted

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._signals)

    @property
    def last_refresh(self) -> datetime | None:
        with self._lock:
            return self._last_refresh
