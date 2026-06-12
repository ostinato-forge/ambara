# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared pytest configuration."""

from __future__ import annotations

import os


def pytest_configure() -> None:
    """Keep test-created Git repos independent of the invoking user's config."""

    os.environ.setdefault("GIT_CONFIG_GLOBAL", os.devnull)
    os.environ.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    os.environ.setdefault("GIT_AUTHOR_NAME", "Ambara Tests")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "tests@example.invalid")
    os.environ.setdefault("GIT_COMMITTER_NAME", "Ambara Tests")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "tests@example.invalid")
