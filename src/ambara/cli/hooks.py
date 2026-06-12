# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Git hook installation CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click


def register_hook_commands(main: click.Group) -> None:
    @main.command("install-hook")
    @click.option(
        "--global",
        "global_hook",
        is_flag=True,
        help="Install as global git hook template",
    )
    @click.option("--force", is_flag=True, help="Overwrite existing hook")
    @click.option(
        "--with-pre-push",
        is_flag=True,
        help="Also install pre-push hook for auto-flush",
    )
    def install_hook(global_hook: bool, force: bool, with_pre_push: bool) -> None:
        """Install the ambara post-commit hook for ambient capture."""
        hook_content = (
            "#!/bin/sh\n"
            "# Ambara post-commit hook — captures ambara: commits\n"
            "MESSAGE=$(git log -1 --format=%B)\n"
            "COMMIT=$(git rev-parse HEAD)\n"
            "AUTHOR=$(git config user.email)\n"
            'ambara capture --message "$MESSAGE" --commit "$COMMIT"'
            ' --author "$AUTHOR" 2>/dev/null || true\n'
        )
        if global_hook:
            result = subprocess.run(
                ["git", "config", "--global", "core.hooksPath"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                hooks_dir = Path(result.stdout.strip())
            else:
                hooks_dir = Path.home() / ".git-hooks"
            hooks_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "config", "--global", "core.hooksPath", str(hooks_dir)],
                check=True,
            )
        else:
            hooks_dir = Path(".git") / "hooks"
            if not hooks_dir.exists():
                click.echo("Error: not in a git repository", err=True)
                raise SystemExit(1)

        hook_path = hooks_dir / "post-commit"
        if hook_path.exists() and not force:
            click.echo(
                f"Hook already exists at {hook_path}. Use --force to overwrite.",
                err=True,
            )
            raise SystemExit(1)

        hook_path.write_text(hook_content)
        hook_path.chmod(0o755)
        click.echo(f"Installed post-commit hook at {hook_path}")

        if with_pre_push:
            pre_push_content = (
                "#!/bin/sh\n"
                "# Ambara pre-push hook — flushes pending captures before push\n"
                "ambara flush 2>/dev/null || true\n"
            )
            pre_push_path = hooks_dir / "pre-push"
            if pre_push_path.exists() and not force:
                click.echo(
                    f"Pre-push hook exists at {pre_push_path}. Use --force to overwrite.",
                    err=True,
                )
                raise SystemExit(1)
            else:
                pre_push_path.write_text(pre_push_content)
                pre_push_path.chmod(0o755)
                click.echo(f"Installed pre-push hook at {pre_push_path}")
