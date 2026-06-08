# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI commands for small, self-contained local operations.

Registered onto the main CLI via ``register_local_commands`` so the command
bodies live outside the historical ``cli.py`` facade.
"""

from __future__ import annotations

import click

from ambara.core.privacy import generate_privacy_salt


def register_local_commands(main: click.Group) -> None:
    """Register small local-operation commands onto the main CLI."""

    @main.command("privacy-salt")
    @click.option(
        "--bytes",
        "num_bytes",
        default=32,
        show_default=True,
        type=click.IntRange(16, 128),
        help="Number of random bytes to generate.",
    )
    def privacy_salt(num_bytes: int) -> None:
        """Generate a AMBARA_PRIVACY_SALT value for opaque identity hashing."""
        click.echo(generate_privacy_salt(num_bytes=num_bytes))
