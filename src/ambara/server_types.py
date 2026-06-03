"""Shared server helper types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.git.config import PRSignalsConfig

SignalFetcher = Callable[[PRSignalsConfig], Sequence[PRSignal | CoordinationSignal]]
T = TypeVar("T")


class BlockingRunner(Protocol):
    def __call__(self, function: Callable[[], T]) -> Awaitable[T]: ...
