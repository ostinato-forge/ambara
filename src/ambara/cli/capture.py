# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Local capture queue commands for the CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click

from ambara.git.repo import ensure_repo, fetch_all


def register_capture_commands(main: click.Group) -> None:
    @main.command()
    @click.option("--message", "-m", required=True, help="Commit message to process")
    @click.option("--commit", default="unknown", help="Source commit SHA")
    @click.option("--author", default="unknown", help="Source commit author email")
    @click.option(
        "--repo-slug", default=None, help="Source repo slug (defaults to current dir name)"
    )
    def capture(message: str, commit: str, author: str, repo_slug: str | None) -> None:
        """Process a commit message through the ambara capture pipeline."""
        from ambara.capture.extract import parse_commit_message
        from ambara.capture.pending import save_pending

        parsed = parse_commit_message(message)
        if parsed is None:
            click.echo("No ambara: prefix found — nothing to capture.")
            return

        if repo_slug is None:
            repo_slug = Path.cwd().name

        git_dir = _local_git_dir(Path.cwd())
        try:
            save_pending(str(git_dir), commit, message, author=author, repo_slug=repo_slug)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(
            f'[ambara] queued: "{parsed.title}" (type={parsed.entry_type}, level={parsed.level})'
        )

    @main.command()
    @click.argument("message")
    @click.option("--expires", default="2h", help="Expiry duration (e.g. 2h, 30m)")
    def active(message: str, expires: str) -> None:
        """Broadcast active status without a commit."""
        click.echo(f'[ambara] active: "{message}" (expires in {expires})')
        click.echo("Note: requires AMBARA_KNOWLEDGE_REMOTE to be configured.")

    @main.command()
    @click.option("--dry-run", is_flag=True, help="List pending captures without writing.")
    def flush(dry_run: bool) -> None:
        """Flush pending captures from the offline queue."""
        from ambara.capture.pending import list_pending, remove_pending
        from ambara.capture.pipeline import run_capture
        from ambara.git.config import load_config_from_env

        git_dir = _local_git_dir(Path.cwd())

        pending = list_pending(str(git_dir))
        if not pending:
            click.echo("No pending captures.")
            return

        click.echo(f"Found {len(pending)} pending capture(s).")
        if dry_run:
            for item in pending:
                click.echo(f"  - {item['commit_sha'][:8]}: {item['message'][:60]}")
            return

        try:
            config = load_config_from_env()
            knowledge_repo_path = ensure_repo(config.remote_url, config.cache_dir)
            fetch_all(
                knowledge_repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        processed = 0
        skipped = 0
        failed = 0
        for item in pending:
            commit_sha = item["commit_sha"]
            message = item["message"]
            repo_slug = item.get("repo_slug") or Path.cwd().name
            author = item.get("author") or "unknown"
            try:
                outcome = run_capture(
                    message=message,
                    repo_slug=repo_slug,
                    knowledge_repo_path=knowledge_repo_path,
                    main_branch=config.main_branch,
                    now=datetime.now(UTC),
                    source_commit=commit_sha,
                    source_author=author,
                )
            except Exception as exc:
                failed += 1
                click.echo(f"Failed {commit_sha[:8]}: {exc}", err=True)
                continue

            remove_pending(str(git_dir), commit_sha)
            if outcome is None:
                skipped += 1
                click.echo(f"Skipped {commit_sha[:8]}: already captured or not applicable.")
            else:
                processed += 1
                click.echo(f"Flushed {commit_sha[:8]}: {outcome.entry_id}")

        click.echo(f"Processed {processed}, skipped {skipped}, failed {failed}.")
        if failed:
            raise click.ClickException("one or more pending captures failed; markers were kept")


def _local_git_dir(root: Path) -> Path:
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        content = marker.read_text().strip()
        prefix = "gitdir:"
        if content.startswith(prefix):
            git_dir = Path(content[len(prefix) :].strip())
            return git_dir if git_dir.is_absolute() else (root / git_dir).resolve()
    raise click.ClickException("not in a git repository")
