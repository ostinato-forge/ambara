"""Signal provider protocol — I/O interface for coordination signal sources.

This is the integration point for non-GitHub providers (Jira, Linear,
Slack, Confluence, etc). Each provider maps its domain objects into
CoordinationSignal. The pure classification logic handles them all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from ambara.core.pr_signals import CoordinationSignal


@runtime_checkable
class SignalProvider(Protocol):
    provider_id: str

    def fetch_signals(self, config: dict[str, Any]) -> list[CoordinationSignal]: ...

    def needs_refresh(self, last_fetch: datetime, now: datetime) -> bool: ...
