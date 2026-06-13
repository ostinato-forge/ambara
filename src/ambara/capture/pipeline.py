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
from ambara.core.changes import plan_capture
from ambara.core.content_policy import (
    CallerScope,
    PolicyAction,
    PolicySubject,
    PolicyVerdict,
    WritePolicy,
)
from ambara.core.content_policy_config import default_config
from ambara.core.schema import EntryType, EscalationLevel, SourceMeta
from ambara.git.branch import (
    branch_exists_remote,
    create_branch,
    entry_exists_on_main,
    push_branch_with_retry,
)
from ambara.git.commit import materialize_write

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


def _content_policy_verdict(
    *,
    title: str,
    body: str,
    entry_type: EntryType,
    level: EscalationLevel,
    caller_source: Literal["github_actions", "gitlab_ci", "gh_cli", "unknown"],
    content_policy: WritePolicy | None,
) -> PolicyVerdict:
    policy = content_policy or _CAPTURE_CONTENT_POLICY
    actor_kind: Literal["human", "bot", "ci", "unknown"] = (
        "ci" if caller_source in {"github_actions", "gitlab_ci"} else "bot"
    )
    return policy.evaluate(
        PolicySubject(
            source="ci",
            title=title,
            body=body,
            entry_type=entry_type,
            level=level,
        ),
        CallerScope(source=caller_source, actor_kind=actor_kind),
        now=datetime.now(),
    )


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

    level = parsed.level
    verdict = _content_policy_verdict(
        title=parsed.title,
        body=parsed.body,
        entry_type=parsed.entry_type,
        level=level,
        caller_source=caller_source,
        content_policy=content_policy,
    )
    if verdict.action == PolicyAction.BLOCK:
        raise ValueError(verdict.message)
    if verdict.action == PolicyAction.REQUIRE_REVIEW and level in (
        EscalationLevel.L0,
        EscalationLevel.L1,
    ):
        level = EscalationLevel.L2

    secret_detected = scan_secrets(f"{parsed.title} {parsed.body}", extra_secret_patterns)
    if secret_detected and level in (EscalationLevel.L0, EscalationLevel.L1):
        level = EscalationLevel.L2

    intent = plan_capture(
        entry_type=parsed.entry_type,
        title=parsed.title,
        body=parsed.body,
        entry_id=entry_id,
        level=level,
        now=now,
        source=source,
    )

    if entry_exists_on_main(knowledge_repo_path, intent.path, main_branch):
        return None

    if intent.branch and branch_exists_remote(knowledge_repo_path, intent.branch):
        return None

    if intent.branch is None:
        raise ValueError("Capture pipeline does not handle L0 active entries")

    contradiction_ids: list[str] = []
    try:
        from ambara.core.curation import detect_contradictions
        from ambara.git.repo import load_index_from_repo

        index = load_index_from_repo(knowledge_repo_path, main_branch)
        conflicts = detect_contradictions(
            parsed.title,
            list(index.entries.values()),
            entry_type=parsed.entry_type,
        )
        contradiction_ids = [c.frontmatter.id for c in conflicts]
    except Exception:
        logger.warning("Contradiction detection failed", exc_info=True)

    create_branch(knowledge_repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(knowledge_repo_path, intent)
    push_branch_with_retry(knowledge_repo_path, intent.branch)

    return CaptureOutcome(
        entry_id=entry_id,
        level=level,
        sha=sha,
        branch=intent.branch,
        secret_detected=secret_detected,
        content_policy_action=(
            None
            if verdict.action == PolicyAction.ALLOW and not verdict.rule_ids
            else str(verdict.action)
        ),
        content_policy_rules=verdict.rule_ids,
        content_policy_warning=verdict.warning,
        contradiction_ids=contradiction_ids,
    )
