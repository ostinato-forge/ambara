"""CLI entry point: jurati serve, jurati init, jurati validate."""

from __future__ import annotations

import click


@click.group()
def main() -> None:
    """Jurati — shared team intelligence layer for agentic workflows."""


@main.command()
def serve() -> None:
    """Start the jurati MCP server over stdio."""
    from jurati.server import mcp

    mcp.run(transport="stdio")
