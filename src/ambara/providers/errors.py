# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Provider-specific errors for coordination signal fetches."""

from __future__ import annotations


class SignalProviderError(RuntimeError):
    """Raised when a configured signal source could not be queried."""
