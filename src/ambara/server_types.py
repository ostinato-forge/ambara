# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared server helper types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, TypeVar

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.sources.config import SourceInputsConfig

LegacySignalFetcher = Callable[[SourceInputsConfig], Sequence[PRSignal | CoordinationSignal]]
SignalFetcher = LegacySignalFetcher
T = TypeVar("T")


class BlockingRunner(Protocol):
    def __call__(self, function: Callable[[], T]) -> Awaitable[T]: ...
