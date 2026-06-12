# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Context import commands for the CLI."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from ambara.git.import_context import materialize_context_import
from ambara.import_context import (
    ContextPackError,
    ImportPlan,
    default_import_branch,
    plan_context_import,
    plan_markdown_import,
)


def register_import_commands(main: click.Group) -> None:
    @main.command("import-context")
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Validate and summarize the import without writing files.",
    )
    @click.option(
        "--repo",
        "repo_path",
        default=".",
        show_default=True,
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        help="Path to the Ambara knowledge repo to import into.",
    )
    @click.option(
        "--branch",
        default=None,
        help="Review branch to create when writing the import.",
    )
    @click.option(
        "--base",
        default="HEAD",
        show_default=True,
        help="Base ref for the review branch when writing the import.",
    )
    @click.argument("bundle", type=click.Path(exists=True, dir_okay=False))
    def import_context_cmd(
        bundle: str,
        dry_run: bool,
        repo_path: str,
        branch: str | None,
        base: str,
    ) -> None:
        """Plan an import from a context-pack tarball."""
        try:
            plan = plan_context_import(
                Path(bundle),
                knowledge_repo=Path(repo_path),
                now=datetime.now(UTC),
            )
        except ContextPackError as exc:
            raise click.ClickException(str(exc)) from exc

        _print_import_plan(plan, Path(repo_path), dry_run=dry_run)
        if plan.errors or plan.reject_count:
            sys.exit(1)

        if dry_run:
            return

        try:
            result = materialize_context_import(
                repo_path,
                plan,
                branch=branch or default_import_branch(plan),
                base=base,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo("")
        click.echo("Wrote import review branch:")
        click.echo(f"  branch: {result.branch}")
        click.echo(f"  commit: {result.commit}")
        click.echo(f"  created: {len(result.created_paths)} entries")
        click.echo("")
        click.echo("Next: push this branch and open a review request to merge it.")

    @main.command("import-docs")
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Validate and summarize the import without writing files.",
    )
    @click.option(
        "--repo",
        "repo_path",
        default=".",
        show_default=True,
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        help="Path to the Ambara knowledge repo to import into.",
    )
    @click.option(
        "--branch",
        default=None,
        help="Review branch to create when writing the import.",
    )
    @click.option(
        "--base",
        default="HEAD",
        show_default=True,
        help="Base ref for the review branch when writing the import.",
    )
    @click.option(
        "--mode",
        type=click.Choice(["adr", "rfc", "docs", "obsidian"]),
        default="adr",
        show_default=True,
        help="How to map source Markdown into Ambara entries.",
    )
    @click.option("--project", "projects", multiple=True, help="Project tag to add.")
    @click.option("--tag", "tags", multiple=True, help="Additional tag to add.")
    @click.argument("source", nargs=-1, required=True, type=click.Path(exists=True))
    def import_docs_cmd(
        source: tuple[str, ...],
        dry_run: bool,
        repo_path: str,
        branch: str | None,
        base: str,
        mode: str,
        projects: tuple[str, ...],
        tags: tuple[str, ...],
    ) -> None:
        """Plan an import from allowlisted Markdown files or directories."""
        try:
            plan = plan_markdown_import(
                tuple(Path(item) for item in source),
                knowledge_repo=Path(repo_path),
                now=datetime.now(UTC),
                mode=mode,
                projects=projects,
                tags=tags,
                source_root=Path.cwd(),
            )
        except ContextPackError as exc:
            raise click.ClickException(str(exc)) from exc

        _print_import_plan(plan, Path(repo_path), dry_run=dry_run)
        if plan.errors or plan.reject_count:
            sys.exit(1)

        if dry_run:
            return

        try:
            result = materialize_context_import(
                repo_path,
                plan,
                branch=branch or default_import_branch(plan),
                base=base,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo("")
        click.echo("Wrote import review branch:")
        click.echo(f"  branch: {result.branch}")
        click.echo(f"  commit: {result.commit}")
        click.echo(f"  created: {len(result.created_paths)} entries")
        click.echo("")
        click.echo("Next: push this branch and open a review request to merge it.")


def _print_import_plan(plan: ImportPlan, repo_path: Path, *, dry_run: bool) -> None:
    click.echo("Context import dry run" if dry_run else "Context import plan")
    click.echo(f"{plan.source_label}: {plan.bundle_name}")
    click.echo(f"Knowledge repo: {repo_path}")
    click.echo(
        f"Summary: {plan.create_count} create, {plan.skip_count} skip, {plan.reject_count} reject"
    )

    _print_import_section(plan, "create", "Create")
    _print_import_section(plan, "skip", "Skip")
    _print_import_section(plan, "reject", "Reject")

    if plan.errors:
        click.echo("")
        click.echo("Repository errors:")
        for error in plan.errors:
            click.echo(f"  - {error}")

    if dry_run:
        click.echo("")
        click.echo("No files written.")


def _print_import_section(plan: ImportPlan, action: str, title: str) -> None:
    items = [item for item in plan.actions if item.action == action]
    if not items:
        return

    click.echo("")
    click.echo(f"{title}:")
    for item in items:
        if item.destination_path:
            click.echo(
                f"  - {item.source_path} -> {item.destination_path} "
                f"({item.entry_type}, {item.level}): {item.reason}"
            )
        else:
            click.echo(f"  - {item.source_path}: {item.reason}")
        for error in item.errors:
            click.echo(f"      {error}")
