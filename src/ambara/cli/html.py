# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI command for the static HTML knowledge browser.

Registered onto the main CLI via ``register_html_command`` so the command body
lives outside the historical ``cli/__init__.py`` facade.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ambara.static_html import generate_static_html


def register_html_command(main: click.Group) -> None:
    """Register the ``html`` command onto the main CLI."""

    @main.command("html")
    @click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
    @click.option(
        "--output",
        "output_path",
        default=None,
        type=click.Path(file_okay=False),
        help="Output directory. Defaults to <knowledge-repo>/_site.",
    )
    def html_cmd(path: str, output_path: str | None) -> None:
        """Generate a static HTML browser for a local knowledge repo."""
        try:
            result = generate_static_html(
                Path(path),
                output_dir=Path(output_path) if output_path else None,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Generated {len(result.pages)} page(s) in {result.output_dir}")
        if result.skipped_restricted:
            click.echo(f"Skipped {result.skipped_restricted} restricted entries.")
        if result.errors:
            click.echo("Parse errors:")
            for error in result.errors:
                click.echo(f"  - {error}")
            sys.exit(1)
