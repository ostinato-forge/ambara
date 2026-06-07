# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI commands for the derived local SQLite read model.

Registered onto the main CLI via ``register_read_model_commands`` so the command
bodies live outside the historical ``cli.py`` facade.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from ambara.core.schema import Visibility
from ambara.read_model.sqlite import (
    default_db_path,
    query_read_model,
    rebuild_read_model,
)


def register_read_model_commands(main: click.Group) -> None:
    """Register the ``read-model`` command group onto the main CLI."""

    @main.group("read-model")
    def read_model_cmd() -> None:
        """Manage derived local read models."""

    @read_model_cmd.command("rebuild")
    @click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
    @click.option(
        "--db",
        "db_path",
        default=None,
        type=click.Path(dir_okay=False),
        help="SQLite output path. Defaults to <knowledge-repo>/.ambara/read-model.sqlite3.",
    )
    def read_model_rebuild(path: str, db_path: str | None) -> None:
        """Rebuild the derived SQLite/FTS read model from a knowledge repo."""
        result = rebuild_read_model(
            Path(path),
            db_path=Path(db_path) if db_path else None,
        )
        click.echo(f"Rebuilt read model: {result.db_path}")
        click.echo(f"Indexed entries: {result.entries_indexed}")
        if result.entries_skipped_restricted:
            click.echo(f"Skipped restricted entries: {result.entries_skipped_restricted}")
        if result.errors:
            click.echo("Parse errors:")
            for error in result.errors:
                click.echo(f"  - {error}")
            sys.exit(1)

    @read_model_cmd.command("query")
    @click.argument("query_text")
    @click.option(
        "--repo",
        "repo_path",
        default=".",
        show_default=True,
        type=click.Path(exists=True, file_okay=False),
        help="Knowledge repo used to locate the default read-model database.",
    )
    @click.option("--db", "db_path", default=None, type=click.Path(exists=True, dir_okay=False))
    @click.option("--limit", default=10, show_default=True, type=click.IntRange(1, 100))
    @click.option(
        "--visibility",
        default=None,
        type=click.Choice([str(item) for item in Visibility]),
        help="Limit results to entries with the given visibility.",
    )
    def read_model_query(
        query_text: str,
        repo_path: str,
        db_path: str | None,
        limit: int,
        visibility: str | None,
    ) -> None:
        """Query the derived SQLite/FTS read model."""
        database = Path(db_path) if db_path else default_db_path(Path(repo_path))
        if not database.exists():
            raise click.ClickException(
                f"Read model not found at {database}. "
                f"Run `ambara read-model rebuild {repo_path}` first."
            )
        results = query_read_model(
            database,
            query_text,
            now=datetime.now(UTC),
            visibility=Visibility(visibility) if visibility else None,
            limit=limit,
        )
        for item in results:
            click.echo(f"{item.id}\t{item.type}\t{item.title}")
