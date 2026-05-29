"""Shared server helper types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from jurati.core.pr_signals import CoordinationSignal, PRSignal
from jurati.git.config import PRSignalsConfig

SignalFetcher = Callable[[PRSignalsConfig], Sequence[PRSignal | CoordinationSignal]]
BlockingRunner = Callable[
    [Callable[[], Sequence[PRSignal | CoordinationSignal]]],
    Awaitable[Sequence[PRSignal | CoordinationSignal]],
]
