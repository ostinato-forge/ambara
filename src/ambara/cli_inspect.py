# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI commands for inspecting and explaining Ambara.

Registered onto the main CLI via ``register_inspect_commands`` so the command
bodies live outside the historical ``cli.py`` facade.
"""

from __future__ import annotations

import click


def register_inspect_commands(main: click.Group) -> None:
    """Register inspection and explanation commands onto the main CLI."""

    @main.command()
    def explain() -> None:
        """Explain what Ambara does in plain language."""
        click.echo(
            "\n".join(
                [
                    "Ambara gives people and AI agents shared, reviewable context backed by git.",
                    "",
                    "It reads:",
                    (
                        "  - project status, decisions, workflows, and principles "
                        "from a knowledge repo"
                    ),
                    "  - local cached content when answering query/read/list requests",
                    "  - derived indexes built from Markdown, not Markdown treated as a database",
                    "",
                    "It writes only when explicitly asked:",
                    "  - record(active): short-lived current work on an active git ref",
                    (
                        "  - record(project): lightweight review branch; a review request "
                        "may be opened later"
                    ),
                    (
                        "  - propose(workflow/decision/principle): reviewed branch; a "
                        "review request may be opened later"
                    ),
                    "  - expire(id): active ref deletion or review branch, depending on entry type",
                    "",
                    "It does not:",
                    "  - log query text",
                    "  - track who read what",
                    "  - infer presence from editor, terminal, or agent activity",
                    "  - bypass normal git provenance or review",
                ]
            )
        )
