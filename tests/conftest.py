# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared pytest configuration."""

from __future__ import annotations

import os

import time_machine

# Fixtures carry fixed timestamps and the code under test measures age against the
# wall clock, so the suite runs at a fixed instant. Without this, "fresh" fixtures
# turn stale as real time passes and tests fail with no code change. The clock still
# ticks forward from this instant so timeouts and durations behave normally.
TEST_CLOCK_START = "2026-06-14T12:00:00Z"

_clock = time_machine.travel(TEST_CLOCK_START, tick=True)


def pytest_configure() -> None:
    """Keep test runs independent of the invoking user's config and the real date."""

    os.environ.setdefault("GIT_CONFIG_GLOBAL", os.devnull)
    os.environ.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    os.environ.setdefault("GIT_AUTHOR_NAME", "Ambara Tests")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "tests@example.invalid")
    os.environ.setdefault("GIT_COMMITTER_NAME", "Ambara Tests")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "tests@example.invalid")
    _clock.start()


def pytest_unconfigure() -> None:
    _clock.stop()
