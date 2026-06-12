# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Posture-check CLI command."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ambara.core.posture import (
    PostureReport,
    apply_gitignore_secret_patterns,
    check_agent_start_guardrails,
)


def register_posture_command(main: click.Group) -> None:
    @main.command("posture-check")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable posture output.")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        help="Path to the repo to check.",
    )
    @click.option(
        "--fix",
        is_flag=True,
        help="Apply safe project-local fixes for auto-fixable findings.",
    )
    def posture_check(as_json: bool, repo_path: str, fix: bool) -> None:
        """Check agent-safe-start secret guardrails."""
        repo = Path(repo_path)
        applied_patterns: tuple[str, ...] = ()
        if fix:
            applied_patterns = apply_gitignore_secret_patterns(repo)

        report = check_agent_start_guardrails(repo)
        if as_json:
            payload = report.to_dict()
            if applied_patterns:
                payload["applied_fixes"] = [
                    {
                        "id": "gitignore.missing-secret-patterns",
                        "paths": [".gitignore"],
                        "patterns": list(applied_patterns),
                    }
                ]
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if applied_patterns:
                click.echo("Applied auto-fix: appended Ambara secret patterns to .gitignore")
                click.echo("")
            click.echo(_render_posture_report(report))

        if not report.agent_start_guardrails_ready:
            sys.exit(1)


def _render_posture_report(report: PostureReport) -> str:
    passed = sum(1 for check in report.checks if check.status == "ok")
    total = len(report.checks)
    if report.agent_start_guardrails_ready:
        return (
            "Ambara agent-safe-start guardrails: ready "
            f"({passed}/{total} checks passed, {report.token_cost})"
        )

    lines = [
        "Ambara agent-safe-start guardrails",
        f"  repo: {report.repo}",
        "  ready for agent start: no",
        f"  check cost: {report.token_cost}",
        "",
        "Errors:",
    ]
    for finding in report.findings:
        lines.append(f"  - {finding.summary}")
        if finding.paths:
            lines.append(f"    paths: {', '.join(finding.paths[:5])}")

    auto_fixable = [finding for finding in report.findings if finding.auto_fixable]
    if auto_fixable:
        lines.extend(["", "Auto-fixable:"])
        for finding in auto_fixable:
            lines.append(f"  - {finding.id}")
        lines.extend(["", "Next:", "  ambara posture-check --fix"])

    return "\n".join(lines)
