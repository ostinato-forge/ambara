# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Side-effecting writer that materializes a RememberPlan onto a review branch.

The pure decision lives in ``core.remember.plan_remember``; this module performs
the idempotent branch/commit/push. It opens a branch and pushes it — it never
opens a pull request (a PR exists where the decision was made; remembering does
not re-review). Used by the ``source promote`` adapter; commit capture keeps its
own thin materialize for test parity.
"""

from __future__ import annotations

from dataclasses import dataclass

from ambara.core.remember import RememberPlan
from ambara.git.branch import (
    branch_exists_remote,
    create_branch,
    entry_exists_on_main,
    push_branch_with_retry,
)
from ambara.git.commit import materialize_write


@dataclass(frozen=True)
class RememberOutcome:
    entry_id: str
    branch: str
    sha: str | None
    reused_existing: bool
    receipt: dict[str, object]


def materialize_remember(
    repo_path: str, plan: RememberPlan, *, main_branch: str
) -> RememberOutcome:
    """Open a review branch for a create-plan, idempotently. Side-effecting."""
    intent = plan.intent
    if plan.action != "create" or intent is None or intent.branch is None:
        raise ValueError("materialize_remember requires a create plan with a branch")

    branch = intent.branch
    if entry_exists_on_main(repo_path, intent.path, main_branch) or branch_exists_remote(
        repo_path, branch
    ):
        return RememberOutcome(
            entry_id=intent.entry_id,
            branch=branch,
            sha=None,
            reused_existing=True,
            receipt={**plan.receipt, "reused_existing": True},
        )

    create_branch(repo_path, branch, f"origin/{main_branch}")
    sha = materialize_write(repo_path, intent)
    push_branch_with_retry(repo_path, branch)
    return RememberOutcome(
        entry_id=intent.entry_id,
        branch=branch,
        sha=sha,
        reused_existing=False,
        receipt={**plan.receipt, "branch": branch, "sha": sha},
    )
