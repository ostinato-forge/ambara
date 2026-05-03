"""CLI entry point: jurati serve, jurati init, jurati validate."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import frontmatter

from jurati.core.index import parse_entry
from jurati.core.paths import TYPE_DIRS
from jurati.core.validate import validate_entry

SCAFFOLD_DIRS = [
    "principles",
    "decisions",
    "workflows",
    "projects",
    "active",
    "archive",
    ".jurati",
]

DEFAULT_CONFIG = """\
schema_version: 1
main_branch: main
active_ref_prefix: jurati/active
"""


@click.group()
def main() -> None:
    """Jurati — shared team intelligence layer for agentic workflows."""


@main.command()
def serve() -> None:
    """Start the jurati MCP server over stdio."""
    from jurati.server import mcp

    mcp.run(transport="stdio")


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
def validate(path: str) -> None:
    """Validate all knowledge entries in a directory."""
    root = Path(path)
    errors: list[str] = []
    seen_ids: dict[str, str] = {}
    entry_count = 0

    for type_dir in TYPE_DIRS.values():
        dir_path = root / type_dir
        if not dir_path.is_dir():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            entry_count += 1
            rel_path = f"{type_dir}/{md_file.name}"
            try:
                post = frontmatter.loads(md_file.read_text())
                entry = parse_entry(rel_path, dict(post.metadata), post.content)
            except Exception as exc:
                errors.append(f"{rel_path}: parse error: {exc}")
                continue

            entry_errors = validate_entry(entry)
            for err in entry_errors:
                errors.append(f"{rel_path}: {err}")

            eid = entry.frontmatter.id
            if eid in seen_ids:
                errors.append(
                    f"{rel_path}: duplicate ID {eid!r} "
                    f"(also in {seen_ids[eid]})"
                )
            else:
                seen_ids[eid] = rel_path

    if errors:
        click.echo(f"Found {len(errors)} error(s) in {entry_count} entries:")
        for err in errors:
            click.echo(f"  - {err}")
        sys.exit(1)
    else:
        click.echo(f"All {entry_count} entries valid.")


@main.command()
@click.argument("path", default=".", type=click.Path())
def init(path: str) -> None:
    """Initialize a knowledge repo scaffold."""
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)

    for dirname in SCAFFOLD_DIRS:
        (root / dirname).mkdir(exist_ok=True)

    config_path = root / ".jurati" / "config.yaml"
    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG)
        click.echo(f"Created {config_path}")
    else:
        click.echo(f"Config already exists: {config_path}")

    click.echo(f"Knowledge repo initialized at {root}")
