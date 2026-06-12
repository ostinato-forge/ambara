# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI write pipeline — content policy + git write operations.

Shared by `record` and `propose` CLI commands. No ServerState dependency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

import click

from ambara.core.changes import WriteIntent
from ambara.core.content_policy import (
    CallerScope,
    PolicyAction,
    PolicySubject,
    WritePolicy,
)
from ambara.core.content_policy_config import default_config
from ambara.core.schema import EntryType, EscalationLevel, Visibility
from ambara.git.branch import (
    cleanup_branch,
    create_branch,
    push_active_ref,
    push_branch,
)
from ambara.git.commit import materialize_write


def gen_entry_id() -> str:
    return uuid.uuid4().hex[:12]


def check_content_policy(
    *,
    source: Literal["record", "propose"],
    title: str,
    content: str,
    entry_type: EntryType | None = None,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    visibility: Visibility | None = None,
) -> None:
    policy = WritePolicy(default_config())
    subject = PolicySubject(
        source=source,
        title=title,
        body=content,
        entry_type=entry_type,
        level=level,
        projects=tuple(projects or []),
        tags=tuple(tags or []),
        visibility=visibility,
    )
    verdict = policy.evaluate(subject, CallerScope(source="gh_cli"), now=datetime.now(UTC))

    if verdict.action == PolicyAction.BLOCK:
        raise click.ClickException(
            f"Content blocked by policy: {verdict.message}\nRemove sensitive material and retry."
        )
    if verdict.action == PolicyAction.ALLOW_WITH_WARNING:
        click.echo(f"Warning: {verdict.warning}", err=True)


def do_active_write(repo_path: str, intent: WriteIntent, main_branch: str) -> str:
    assert intent.branch is not None
    create_branch(repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(repo_path, intent)
    push_active_ref(repo_path, intent.branch, sha)
    cleanup_branch(repo_path, intent.branch, main_branch)
    return sha


def do_branch_write(repo_path: str, intent: WriteIntent, main_branch: str) -> str:
    assert intent.branch is not None
    create_branch(repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(repo_path, intent)
    push_branch(repo_path, intent.branch)
    cleanup_branch(repo_path, intent.branch, main_branch)
    return sha
