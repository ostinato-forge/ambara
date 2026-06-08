# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared server helper types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

T = TypeVar("T")


class BlockingRunner(Protocol):
    def __call__(self, function: Callable[[], T]) -> Awaitable[T]: ...
