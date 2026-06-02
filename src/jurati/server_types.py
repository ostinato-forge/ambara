"""Shared server helper types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from jurati.core.pr_signals import CoordinationSignal, PRSignal
from jurati.git.config import PRSignalsConfig

SignalFetcher = Callable[[PRSignalsConfig], Sequence[PRSignal | CoordinationSignal]]
T = TypeVar("T")


class BlockingRunner(Protocol):
    def __call__(self, function: Callable[[], T]) -> Awaitable[T]: ...
