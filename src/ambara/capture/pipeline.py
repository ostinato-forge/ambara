# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""End-to-end capture orchestration for the ambara: commit convention."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ambara.capture.extract import derive_entry_id, parse_commit_message, scan_secrets
from ambara.core.content_policy import CallerScope, WritePolicy
from ambara.core.content_policy_config import default_config
from ambara.core.remember import RememberCandidate, plan_remember
from ambara.core.schema import Entry, EscalationLevel, SourceMeta
from ambara.git.remember import materialize_remember

logger = logging.getLogger(__name__)
_CAPTURE_CONTENT_POLICY = WritePolicy(default_config())


@dataclass(frozen=True)
class CaptureOutcome:
    entry_id: str
    level: EscalationLevel
    sha: str
    branch: str | None
    secret_detected: bool
    content_policy_action: str | None = None
    content_policy_rules: tuple[str, ...] = ()
    content_policy_warning: str | None = None
    contradiction_ids: list[str] = field(default_factory=list)


def run_capture(
    *,
    message: str,
    repo_slug: str,
    knowledge_repo_path: str,
    main_branch: str,
    now: datetime,
    source_commit: str,
    source_author: str,
    extra_secret_patterns: list[re.Pattern[str]] | None = None,
    caller_source: Literal["github_actions", "gitlab_ci", "gh_cli", "unknown"] = "unknown",
    content_policy: WritePolicy | None = None,
) -> CaptureOutcome | None:
    parsed = parse_commit_message(message)
    if parsed is None:
        return None

    entry_id = derive_entry_id(repo_slug, parsed.title, commit_sha=source_commit)
    source = SourceMeta(repo=repo_slug, commit=source_commit, author=source_author)

    secret_detected = scan_secrets(f"{parsed.title} {parsed.body}", extra_secret_patterns)
    actor_kind: Literal["human", "bot", "ci", "unknown"] = (
        "ci" if caller_source in {"github_actions", "gitlab_ci"} else "bot"
    )
    candidate = RememberCandidate(
        kind="capture",
        entry_id=entry_id,
        title=parsed.title,
        body=parsed.body,
        entry_type=parsed.entry_type,
        requested_level=parsed.level,
        branch_prefix="ambara",
        source_meta=source,
        secrets_present=secret_detected,
    )
    plan = plan_remember(
        candidate,
        index_entries=_load_index_entries(knowledge_repo_path, main_branch),
        content_policy=content_policy or _CAPTURE_CONTENT_POLICY,
        now=now,
        caller=CallerScope(source=caller_source, actor_kind=actor_kind),
    )
    if plan.action == "reject":
        raise ValueError(plan.reject_reasons[0])

    intent = plan.intent
    if intent is None:
        raise ValueError("Capture pipeline produced no write intent")
    if intent.branch is None:
        raise ValueError("Capture pipeline does not handle L0 active entries")

    outcome = materialize_remember(knowledge_repo_path, plan, main_branch=main_branch)
    if outcome.reused_existing:
        return None
    assert outcome.sha is not None  # non-reuse path always has a real sha
    sha = outcome.sha

    return CaptureOutcome(
        entry_id=entry_id,
        level=plan.level,
        sha=sha,
        branch=intent.branch,
        secret_detected=secret_detected,
        content_policy_action=(
            None
            if plan.policy_action == "allow" and not plan.redaction_rule_ids
            else plan.policy_action
        ),
        content_policy_rules=plan.redaction_rule_ids,
        content_policy_warning=plan.policy_warning,
        contradiction_ids=list(plan.contradiction_ids),
    )


def _load_index_entries(repo_path: str, main_branch: str) -> list[Entry]:
    """Load durable entries for contradiction detection; empty list + warn on failure."""
    try:
        from ambara.git.repo import load_index_from_repo

        index = load_index_from_repo(repo_path, main_branch)
        return list(index.entries.values())
    except Exception:
        logger.warning("Index load for contradiction detection failed", exc_info=True)
        return []
