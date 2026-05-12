"""Fixture-backed PR signals for repeatable local coordination gates."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

from jurati.core.pr_signals import PathStatus, PRSignal
from jurati.git.config import PRSignalsConfig

logger = logging.getLogger(__name__)

_BODY_EXCERPT_LIMIT = 500
_PATH_STATUSES = {"available", "unavailable", "disabled"}
_STATES = {"open", "merged", "closed"}


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _derive_target_areas(paths: tuple[str, ...]) -> tuple[str, ...]:
    areas: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) >= 2:
            areas.add("/".join(parts[:2]))
    return tuple(sorted(areas))


def _state(value: object) -> Literal["open", "merged", "closed"]:
    raw = str(value or "open").lower()
    if raw in _STATES:
        return cast(Literal["open", "merged", "closed"], raw)
    return "open"


def _path_status(value: object, *, default: PathStatus) -> PathStatus:
    raw = str(value or default).lower()
    if raw in _PATH_STATUSES:
        return cast(PathStatus, raw)
    return default


def _parse_signal(raw: object, config: PRSignalsConfig, *, now: datetime) -> PRSignal | None:
    if not isinstance(raw, dict):
        return None

    repo = str(raw.get("repo", "")).strip()
    if repo not in config.repos:
        return None

    labels = _string_list(raw.get("labels", []))
    if config.label not in labels:
        return None

    updated_at = _parse_datetime(raw.get("updated_at")) or now
    cutoff = now - timedelta(days=config.recency_days)
    if updated_at < cutoff:
        return None

    try:
        number = int(str(raw.get("number", 0)))
    except ValueError:
        return None
    if number <= 0:
        return None

    provider = str(raw.get("provider", "github"))
    if provider != "github":
        logger.warning("Skipping unsupported PR signal fixture provider: %s", provider)
        return None

    if config.include_changed_paths:
        changed_paths = _string_list(raw.get("changed_paths", []))
        default_status: PathStatus = "available" if changed_paths else "unavailable"
        changed_paths_status = _path_status(raw.get("changed_paths_status"), default=default_status)
    else:
        changed_paths = ()
        changed_paths_status = "disabled"

    if config.include_body_excerpt:
        body = str(raw.get("body_excerpt", raw.get("body", "")) or "")
        body_excerpt = body[:_BODY_EXCERPT_LIMIT] if body else None
    else:
        body_excerpt = None

    created_at = _parse_datetime(raw.get("created_at")) or updated_at
    target_areas = _string_list(raw.get("target_areas", [])) or _derive_target_areas(changed_paths)

    return PRSignal(
        signal_id=str(raw.get("signal_id") or f"github:{repo}:pull:{number}"),
        provider="github",
        repo=repo,
        number=number,
        url=str(raw.get("url") or f"https://github.com/{repo}/pull/{number}"),
        title=str(raw.get("title", "")),
        body_excerpt=body_excerpt,
        author=str(raw.get("author", "unknown")),
        state=_state(raw.get("state")),
        labels=labels,
        created_at=created_at,
        updated_at=updated_at,
        merged_at=_parse_datetime(raw.get("merged_at")),
        changed_paths=changed_paths,
        target_areas=target_areas,
        changed_paths_status=changed_paths_status,
    )


def fetch_fixture_signals(config: PRSignalsConfig) -> list[PRSignal]:
    """Read explicit local PR-signal fixtures.

    The fixture format is either a JSON array or an object with a ``signals``
    array. Fixtures are filtered through the same configured repo and label
    privacy boundary as live provider reads.
    """
    if not config.fixture_path:
        return []

    fixture_path = Path(config.fixture_path).expanduser()
    try:
        payload = json.loads(fixture_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read PR signal fixture %s: %s", fixture_path, exc)
        return []

    raw_signals: object = payload.get("signals", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_signals, list):
        logger.warning("PR signal fixture %s must be a list or contain signals[]", fixture_path)
        return []

    now = datetime.now(UTC)
    signals: list[PRSignal] = []
    for raw in raw_signals:
        signal = _parse_signal(raw, config, now=now)
        if signal is not None:
            signals.append(signal)
    return signals
