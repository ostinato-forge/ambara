# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Scope mute and lifecycle cleanup commands for the CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click

from ambara.cli_project_config import PROJECT_TEAM_CONFIG
from ambara.cli_setup_diagnostics import _print_muted_scope_summary
from ambara.cli_util import _dump_yaml_mapping, _load_yaml_mapping
from ambara.core.schema import EntryType, EscalationLevel
from ambara.core.scope_policy import ScopeMutePolicy


def register_scope_commands(main: click.Group) -> None:
    @main.command("mute-scope")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Project repo to update.",
    )
    @click.option("--project", "projects", multiple=True, help="Project or project key to mute.")
    @click.option("--repo", "repos", multiple=True, help="Source repo slug to mute.")
    @click.option(
        "--source-input",
        "--signal-source",
        "source_inputs",
        multiple=True,
        help="Source input/provider to mute. --signal-source is a legacy alias.",
    )
    @click.option("--tag", "tags", multiple=True, help="Entry tag or source label to mute.")
    def mute_scope_cmd(
        repo_path: str,
        projects: tuple[str, ...],
        repos: tuple[str, ...],
        source_inputs: tuple[str, ...],
        tags: tuple[str, ...],
    ) -> None:
        """Mute local project/repo/source-input/tag scopes without deleting knowledge."""
        policy = _scope_policy_from_cli(
            projects=projects,
            repos=repos,
            source_inputs=source_inputs,
            tags=tags,
        )
        if policy.is_empty():
            raise click.ClickException(
                "Pass at least one scope: --project, --repo, --source-input, or --tag."
            )

        repo = Path(repo_path)
        config_path, updated = _update_project_muted_scopes(repo, policy, remove=False)
        click.echo(f"Muted Ambara scope(s) for {repo}.")
        click.echo(f"Updated {config_path}.")
        _print_muted_scope_summary(updated, prefix="  ")

    @main.command("unmute-scope")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Project repo to update.",
    )
    @click.option("--project", "projects", multiple=True, help="Project or project key to unmute.")
    @click.option("--repo", "repos", multiple=True, help="Source repo slug to unmute.")
    @click.option(
        "--source-input",
        "--signal-source",
        "source_inputs",
        multiple=True,
        help="Source input/provider to unmute. --signal-source is a legacy alias.",
    )
    @click.option("--tag", "tags", multiple=True, help="Entry tag or source label to unmute.")
    def unmute_scope_cmd(
        repo_path: str,
        projects: tuple[str, ...],
        repos: tuple[str, ...],
        source_inputs: tuple[str, ...],
        tags: tuple[str, ...],
    ) -> None:
        """Unmute local project/repo/source-input/tag scopes."""
        policy = _scope_policy_from_cli(
            projects=projects,
            repos=repos,
            source_inputs=source_inputs,
            tags=tags,
        )
        if policy.is_empty():
            raise click.ClickException(
                "Pass at least one scope: --project, --repo, --source-input, or --tag."
            )

        repo = Path(repo_path)
        config_path, updated = _update_project_muted_scopes(repo, policy, remove=True)
        click.echo(f"Unmuted Ambara scope(s) for {repo}.")
        click.echo(f"Updated {config_path}.")
        _print_muted_scope_summary(updated, prefix="  ")

    @main.command("retire-scope")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Knowledge repo checkout to update.",
    )
    @click.option("--project", "projects", multiple=True, help="Project or project key to retire.")
    @click.option("--repo", "repos", multiple=True, help="Source repo slug to retire.")
    @click.option("--tag", "tags", multiple=True, help="Entry tag to retire.")
    @click.option("--branch", default=None, help="Review branch name to create.")
    @click.option("--dry-run", is_flag=True, help="Print matching entries without writing.")
    def retire_scope_cmd(
        repo_path: str,
        projects: tuple[str, ...],
        repos: tuple[str, ...],
        tags: tuple[str, ...],
        branch: str | None,
        dry_run: bool,
    ) -> None:
        """Retire matching knowledge on a review branch without rewriting history."""
        from ambara.git.lifecycle import (
            collect_retire_scope_matches,
            default_retire_scope_branch,
            materialize_retire_scope,
        )

        policy = _scope_policy_from_cli(projects=projects, repos=repos, tags=tags)
        if policy.is_empty():
            raise click.ClickException("Pass at least one scope: --project, --repo, or --tag.")

        now = datetime.now(UTC)
        repo = Path(repo_path)
        try:
            matches = collect_retire_scope_matches(str(repo), policy)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        if not matches:
            click.echo("No active entries matched the requested scope.")
            return

        click.echo(f"Matched {len(matches)} entr{'y' if len(matches) == 1 else 'ies'} to retire:")
        for match in matches:
            click.echo(f"  - {match.entry_id} ({match.entry_type}) {match.path} -> {match.action}")

        if dry_run:
            click.echo("No files written.")
            return

        branch_name = branch or default_retire_scope_branch(now)
        try:
            result = materialize_retire_scope(
                str(repo),
                policy,
                branch=branch_name,
                now=now,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(f"Retired scope on branch {result.branch} ({result.commit[:8]}).")
        click.echo(f"Lifecycle report: {result.report_path}")
        click.echo(
            "No review request was created. Open one if you want to merge this lifecycle cleanup."
        )

    @main.command("clear")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Knowledge repo checkout to update.",
    )
    @click.option(
        "--all",
        "all_entries",
        is_flag=True,
        help="Clear all current entries; restricted entries require --include-restricted.",
    )
    @click.option(
        "--type",
        "entry_types",
        multiple=True,
        type=click.Choice([str(value) for value in EntryType]),
        help="Entry type to clear.",
    )
    @click.option(
        "--level",
        "levels",
        multiple=True,
        type=click.Choice([str(value) for value in EscalationLevel]),
        help="Escalation level to clear.",
    )
    @click.option("--project", "projects", multiple=True, help="Project or project key to clear.")
    @click.option("--repo", "repos", multiple=True, help="Source repo slug to clear.")
    @click.option("--tag", "tags", multiple=True, help="Entry tag to clear.")
    @click.option(
        "--include-restricted",
        is_flag=True,
        help="Include restricted entries in the reviewed cleanup branch.",
    )
    @click.option("--branch", default=None, help="Review branch name to create.")
    @click.option("--dry-run", is_flag=True, help="Print matching entries without writing.")
    def clear_cmd(
        repo_path: str,
        all_entries: bool,
        entry_types: tuple[str, ...],
        levels: tuple[str, ...],
        projects: tuple[str, ...],
        repos: tuple[str, ...],
        tags: tuple[str, ...],
        include_restricted: bool,
        branch: str | None,
        dry_run: bool,
    ) -> None:
        """Bulk-clear current context on a review branch without deleting history."""
        from ambara.git.lifecycle import (
            ClearEntriesFilter,
            collect_clear_entries_matches,
            default_clear_entries_branch,
            materialize_clear_entries,
        )

        filters = ClearEntriesFilter(
            entry_types=tuple(EntryType(value) for value in entry_types),
            levels=tuple(EscalationLevel(value) for value in levels),
            projects=projects,
            repos=repos,
            tags=tags,
            include_restricted=include_restricted,
        )
        if all_entries and filters.has_selectors():
            raise click.ClickException("Use --all by itself, or omit --all and pass filters.")
        if not all_entries and not filters.has_selectors():
            raise click.ClickException(
                "Pass --all or at least one filter: --type, --level, --project, --repo, or --tag."
            )

        now = datetime.now(UTC)
        repo = Path(repo_path)
        try:
            matches = collect_clear_entries_matches(str(repo), filters)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        if not matches:
            click.echo("No current entries matched the clear filters.")
            return

        click.echo(f"Matched {len(matches)} entr{'y' if len(matches) == 1 else 'ies'} to clear:")
        for match in matches:
            click.echo(
                f"  - {match.entry_id} ({match.entry_type}/{match.level}, "
                f"{match.sensitivity}) {match.path} -> {match.action}"
            )

        if dry_run:
            click.echo("No files written.")
            return

        branch_name = branch or default_clear_entries_branch(now)
        try:
            result = materialize_clear_entries(
                str(repo),
                filters,
                branch=branch_name,
                now=now,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(f"Cleared context on branch {result.branch} ({result.commit[:8]}).")
        click.echo(f"Lifecycle report: {result.report_path}")
        click.echo(
            "No review request was created. Open one if you want to merge this lifecycle cleanup."
        )


def _scope_policy_from_cli(
    *,
    projects: tuple[str, ...] = (),
    repos: tuple[str, ...] = (),
    source_inputs: tuple[str, ...] = (),
    signal_sources: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
) -> ScopeMutePolicy:
    return ScopeMutePolicy.from_raw(
        {
            "projects": list(projects),
            "repos": list(repos),
            "source_inputs": list(source_inputs),
            "signal_sources": list(signal_sources),
            "tags": list(tags),
        }
    )


def _update_project_muted_scopes(
    repo: Path, policy: ScopeMutePolicy, *, remove: bool
) -> tuple[Path, ScopeMutePolicy]:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    current = ScopeMutePolicy.from_raw(data.get("muted_scopes"))
    updated = current.without(policy) if remove else current.merge(policy)
    data.setdefault("schema_version", 1)
    if updated.is_empty():
        data.pop("muted_scopes", None)
    else:
        data["muted_scopes"] = updated.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    return path, updated
