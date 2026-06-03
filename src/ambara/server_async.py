# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Async bridges for MCP handlers that need blocking git/provider work."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import cast

import anyio


async def run_blocking[T](function: Callable[[], T]) -> T:
    """Run blocking work off the event loop without relying on selector wakeups."""

    result_queue: queue.Queue[tuple[bool, T | BaseException]] = queue.Queue()

    def worker() -> None:
        try:
            result_queue.put((True, function()))
        except BaseException as exc:
            result_queue.put((False, exc))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            ok, value = result_queue.get_nowait()
            break
        except queue.Empty:
            await anyio.sleep(0.01)

    if ok:
        return cast(T, value)
    raise cast(BaseException, value)
