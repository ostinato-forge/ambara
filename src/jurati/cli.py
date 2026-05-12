"""CLI entry point: jurati serve, jurati init, jurati validate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import frontmatter

from jurati.core.graph import validate_entry_links
from jurati.core.import_context import (
    ContextPackError,
    ImportPlan,
    default_import_branch,
    plan_context_import,
)
from jurati.core.index import Index, parse_entry
from jurati.core.paths import TYPE_DIRS
from jurati.core.schema import EntryStatus, EntryType, Sensitivity, Visibility
from jurati.core.static_html import generate_static_html
from jurati.core.validate import is_expired, validate_entry
from jurati.git.import_context import materialize_context_import
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo, repo_cache_path
from jurati.read_model.sqlite import (
    default_db_path,
    query_read_model,
    rebuild_read_model,
)

SCAFFOLD_DIRS = [
    "principles",
    "decisions",
    "workflows",
    "projects",
    "active",
    "archive",
    ".jurati",
]

DEFAULT_MCP_SERVER_NAME = "jurati"

READ_ONLY_MCP_TOOL_NAMES = [
    "context",
    "query",
    "search",
    "sync",
    "status",
    "read",
    "list_entries",
    "explain",
    "validate",
    "hygiene",
]

WRITE_MCP_TOOL_NAMES = [
    "record",
    "propose",
    "expire",
]

READ_ONLY_MCP_TOOLS = [
    f"mcp__{DEFAULT_MCP_SERVER_NAME}__{tool}" for tool in READ_ONLY_MCP_TOOL_NAMES
]

WRITE_MCP_TOOLS = [f"mcp__{DEFAULT_MCP_SERVER_NAME}__{tool}" for tool in WRITE_MCP_TOOL_NAMES]

JURATI_CLAUDE_SECTION_HEADING = "## Jurati — Team Knowledge"


@dataclass(frozen=True)
class StartupDiagnostics:
    claude_md_present: bool
    startup_contract_present: bool
    settings_present: bool
    read_only_allowed: bool
    write_tools_allowed: bool
    missing_read_only_tools: tuple[str, ...]


@dataclass(frozen=True)
class MCPServerDefinition:
    name: str
    scope: str
    path: Path
    command: str | None
    args: tuple[str, ...]
    remote: str | None


@dataclass(frozen=True)
class MCPConfigDiagnostics:
    definitions: tuple[MCPServerDefinition, ...]
    read_errors: tuple[str, ...]
    collision_names: tuple[str, ...]


DEFAULT_CONFIG = """\
schema_version: 1
main_branch: main
active_ref_prefix: jurati/active
levels:
  active: [L0]
  project: [L1]
  workflow: [L2]
  decision: [L2, L3]
  principle: [L3]
review:
  low_ceremony_labels: [jurati-record]
  required_review_levels: [L2, L3]
expiry:
  active_ttl_hours: 72
active_refs_enabled: true
"""

STARTER_TIMESTAMP = "2026-05-03T00:00:00Z"

STARTER_README = """\
# Jurati Knowledge Repo

This repository is shared context for people and AI coding agents.

Jurati stores durable knowledge as markdown files with YAML frontmatter. Agents
query this repo before they start work, record short-lived active context while
they work, and propose lasting decisions or workflows through pull requests.

What goes here:

- `active/` - short-lived current work and handoff notes
- `projects/` - project status, current goals, and useful context
- `workflows/` - how your team does recurring work
- `decisions/` - design decisions and rationale
- `principles/` - long-lived engineering principles

What does not go here:

- secrets, credentials, or private customer data
- query logs, read receipts, or participation tracking
- raw chat transcripts that have not been curated into useful knowledge

Start with:

```bash
jurati validate .
```
"""

STARTER_PROJECT = f"""\
---
schema_version: 1
id: first-shared-context
title: First shared context
type: project
level: L1
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [jurati]
tags: [onboarding]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Use this entry as a simple first example. Replace it with real project context:
what is in flight, what is blocked, and what an agent should know before
helping in this repository.
"""

STARTER_WORKFLOW = f"""\
---
schema_version: 1
id: daily-shared-context-loop
title: Daily shared context loop
type: workflow
level: L2
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: []
tags: [workflow, onboarding]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Before work starts, query Jurati for prior decisions, project state, and known
workflow preferences.

During work, record only explicit context that should be shared. Active entries
are short-lived and should describe current focus, blockers, or handoff notes.

After work, propose lasting decisions, reusable workflows, or project updates so
the next person or agent does not have to rediscover them.
"""

TRAINING_PROJECT = f"""\
---
schema_version: 1
id: course-refresh-status
title: Course refresh status
type: project
level: L1
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [training]
tags: [course-development, onboarding]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Use this entry to capture the current course goal, lesson scope, known blockers,
SME dependencies, and what an agent should check before helping with content,
labs, reviews, or release preparation.
"""

TRAINING_WORKFLOW = f"""\
---
schema_version: 1
id: course-development-daily-loop
title: Course development daily loop
type: workflow
level: L2
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [training]
tags: [course-development, workflow]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Before writing, query Jurati for prior course decisions, lab constraints,
review expectations, and known validation issues.

During writing, record explicit active context for blockers, assumptions, or
handoffs. Do not record raw scratch work or private reviewer feedback.

Before review, query the review workflow and run the documented validation
commands so peer review starts with fewer mechanical issues.
"""

TRAINING_DECISION = f"""\
---
schema_version: 1
id: validate-labs-before-review
title: Validate labs before review
type: decision
level: L2
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [training]
tags: [validation, review]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Course changes should reach review with a documented validation command already
run, or with an explicit note explaining what blocked validation.
"""

ENGINEERING_PROJECT = f"""\
---
schema_version: 1
id: service-modernization-status
title: Service modernization status
type: project
level: L1
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [engineering]
tags: [engineering, onboarding]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Use this entry to capture active engineering goals, service ownership, rollout
constraints, open risks, and the context an agent should query before changing
code or operational workflows.
"""

ENGINEERING_WORKFLOW = f"""\
---
schema_version: 1
id: engineering-change-loop
title: Engineering change loop
type: workflow
level: L2
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [engineering]
tags: [engineering, workflow]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Before implementation, query Jurati for architecture decisions, release rules,
incident history, and review expectations.

During implementation, record explicit active context for blockers, handoffs, or
investigations that another person or agent should see.

Before merge, query the release or review workflow and run the documented test,
lint, and type-check commands.
"""

ENGINEERING_DECISION = f"""\
---
schema_version: 1
id: capture-architecture-decisions
title: Capture architecture decisions
type: decision
level: L2
status: proposed
created_at: {STARTER_TIMESTAMP}
updated_at: {STARTER_TIMESTAMP}
expires_at: null
projects: [engineering]
tags: [architecture, review]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Architecture choices that affect future implementation, operations, or review
expectations should be proposed as Jurati decisions instead of being left only
in chat, tickets, or transient pull request comments.
"""

STARTER_PACKS: dict[str, dict[str, str]] = {
    "generic": {},
    "training": {
        "projects/course-refresh-status.md": TRAINING_PROJECT,
        "workflows/course-development-daily-loop.md": TRAINING_WORKFLOW,
        "decisions/validate-labs-before-review.md": TRAINING_DECISION,
    },
    "engineering": {
        "projects/service-modernization-status.md": ENGINEERING_PROJECT,
        "workflows/engineering-change-loop.md": ENGINEERING_WORKFLOW,
        "decisions/capture-architecture-decisions.md": ENGINEERING_DECISION,
    },
}


@click.group()
def main() -> None:
    """Jurati: shared agent context for people and AI coding agents."""


@main.command()
@click.option(
    "--check",
    is_flag=True,
    help="Explain what serve would do and verify configuration without starting MCP.",
)
def serve(check: bool) -> None:
    """Start the Jurati MCP server over stdio."""
    if check:
        _serve_check()
        return

    from jurati.server import run_stdio

    run_stdio()


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True))
def validate(path: str) -> None:
    """Validate all knowledge entries in a directory."""
    root = Path(path)
    entry_count, errors = _validate_knowledge_repo(root)

    if errors:
        click.echo(f"Found {len(errors)} error(s) in {entry_count} entries:")
        for err in errors:
            click.echo(f"  - {err}")
        sys.exit(1)
    else:
        click.echo(f"All {entry_count} entries valid.")


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
    help="Path to the Jurati knowledge repo to import into.",
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
    click.echo("Next: push this branch and open a pull request for review.")


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
    help="SQLite output path. Defaults to <knowledge-repo>/.jurati/read-model.sqlite3.",
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
            f"Run `jurati read-model rebuild {repo_path}` first."
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


@main.command()
@click.option(
    "--examples/--no-examples",
    default=True,
    show_default=True,
    help="Create a README and valid starter entries that explain the knowledge model.",
)
@click.option(
    "--pack",
    type=click.Choice(sorted(STARTER_PACKS)),
    default="generic",
    show_default=True,
    help="Optional starter pack to add when examples are enabled.",
)
@click.argument("path", default=".", type=click.Path())
def init(path: str, examples: bool, pack: str) -> None:
    """Initialize a knowledge repo scaffold."""
    root = Path(path)
    created = _init_scaffold(root, examples=examples, pack=pack)

    if created:
        for path_created in created:
            click.echo(f"Created {path_created}")
    else:
        click.echo(f"Scaffold already exists: {root}")

    click.echo(f"Knowledge repo initialized at {root}")
    click.echo("Next: run `jurati validate <path>` and push this directory to a git remote.")


@main.command()
@click.option(
    "--remote",
    envvar="JURATI_KNOWLEDGE_REMOTE",
    help="Git remote URL for the team knowledge repo.",
)
@click.option(
    "--client-slug",
    default="claude-code",
    show_default=True,
    help="Stable client name used for short-lived active refs.",
)
@click.option(
    "--command",
    "command_name",
    default="jurati",
    show_default=True,
    help="Command MCP clients should run.",
)
@click.option(
    "--examples/--no-examples",
    default=True,
    show_default=True,
    help="Create starter entries that explain the knowledge model.",
)
@click.option(
    "--pack",
    type=click.Choice(sorted(STARTER_PACKS)),
    default="generic",
    show_default=True,
    help="Optional starter pack to add when examples are enabled.",
)
@click.argument("path", default="./jurati-knowledge", type=click.Path())
def quickstart(
    path: str,
    remote: str | None,
    client_slug: str,
    command_name: str,
    examples: bool,
    pack: str,
) -> None:
    """Create a starter knowledge repo and print the fastest adoption path."""
    root = Path(path)
    created = _init_scaffold(root, examples=examples, pack=pack)
    _write_settings_json(root, remote=remote)
    entry_count, errors = _validate_knowledge_repo(root)

    click.echo("Jurati quickstart")
    click.echo("")

    if created:
        click.echo("Created:")
        for created_path in created:
            click.echo(f"  - {created_path}")
    else:
        click.echo(f"Scaffold already exists: {root}")

    click.echo("")
    if errors:
        click.echo(f"Validation found {len(errors)} error(s) in {entry_count} entries:")
        for err in errors:
            click.echo(f"  - {err}")
        sys.exit(1)

    click.echo(f"Validated knowledge repo: {entry_count} entries valid.")
    if examples:
        click.echo(f"Starter pack: {pack}")
    click.echo("")
    click.echo("What Jurati will do:")
    click.echo("  - read shared markdown knowledge from this git repo")
    click.echo("  - answer agent queries from a local cache after sync")
    click.echo("  - write only when record/propose/expire is explicitly called")
    click.echo("  - use active refs for short-lived context and PRs for durable knowledge")
    click.echo("  - avoid query logging, read receipts, participation tracking, and telemetry")
    click.echo("")

    if remote:
        click.echo("MCP config:")
        click.echo(_mcp_config_json(remote, client_slug, command_name))
        click.echo("")
        click.echo("Next steps:")
        click.echo(f"  1. cd {root}")
        click.echo("  2. git init")
        click.echo('  3. git add . && git commit -m "docs: initialize jurati knowledge repo"')
        click.echo(f"  4. git remote add origin {remote}")
        click.echo("  5. git push -u origin main")
        click.echo("  6. Paste the MCP config above into your client.")
        click.echo("  7. Run: jurati doctor --check-startup")
        click.echo("  8. Run: jurati serve --check")
    else:
        click.echo("Next steps:")
        click.echo(f"  1. cd {root}")
        click.echo("  2. git init")
        click.echo('  3. git add . && git commit -m "docs: initialize jurati knowledge repo"')
        click.echo("  4. Create a git remote and push this repo.")
        click.echo("  5. Run: jurati mcp-config --remote <git-url>")
        click.echo("  6. Run: jurati doctor --check-startup")
        click.echo("  7. Run: jurati serve --check")


@main.command("mcp-config")
@click.option(
    "--remote",
    envvar="JURATI_KNOWLEDGE_REMOTE",
    required=True,
    help="Git remote URL for the team knowledge repo.",
)
@click.option(
    "--client-slug",
    default="claude-code",
    show_default=True,
    help="Stable client name used for short-lived active refs.",
)
@click.option(
    "--command",
    "command_name",
    default="jurati",
    show_default=True,
    help="Command MCP clients should run.",
)
@click.option(
    "--write-project",
    is_flag=True,
    help="Write or update .mcp.json in the current project with a hash-based server name.",
)
def mcp_config(remote: str, client_slug: str, command_name: str, write_project: bool) -> None:
    """Print or write a collision-resistant MCP config block."""
    payload = _mcp_config_payload(remote, client_slug, command_name)
    if write_project:
        server_name = _write_project_mcp_config(Path(".mcp.json"), payload)
        click.echo(f"Updated .mcp.json with MCP server {server_name!r}.")
        click.echo("Next: run `jurati doctor` to check for duplicate server definitions.")
        return

    click.echo(json.dumps(payload, indent=2))


@main.command()
@click.option(
    "--strict",
    is_flag=True,
    help="Exit with an error when required setup is missing.",
)
@click.option(
    "--check-startup",
    is_flag=True,
    help="Fetch and index the configured knowledge repo to verify sync/context startup.",
)
def doctor(strict: bool, check_startup: bool) -> None:
    """Explain Jurati setup and check whether this machine is ready."""
    ready = _print_doctor(check_startup=check_startup)
    if strict and not ready:
        raise click.ClickException("Jurati is not ready; fix the missing items above.")


@main.command()
def explain() -> None:
    """Explain what Jurati does in plain language."""
    click.echo(
        "\n".join(
            [
                "Jurati gives people and AI agents shared, reviewable context backed by git.",
                "",
                "It reads:",
                "  - project status, decisions, workflows, and principles from a knowledge repo",
                "  - local cached content when answering query/read/list requests",
                "  - derived indexes built from Markdown, not Markdown treated as a database",
                "",
                "It writes only when explicitly asked:",
                "  - record(active): short-lived current work on an active git ref",
                "  - record(project): lightweight pull request",
                "  - propose(workflow/decision/principle): reviewed pull request",
                "  - expire(id): active ref deletion or pull request, depending on entry type",
                "",
                "It does not:",
                "  - log query text",
                "  - track who read what",
                "  - infer presence from editor, terminal, or agent activity",
                "  - bypass normal git provenance or review",
            ]
        )
    )


@main.command("install-hook")
@click.option("--global", "global_hook", is_flag=True, help="Install as global git hook template")
@click.option("--force", is_flag=True, help="Overwrite existing hook")
@click.option("--with-pre-push", is_flag=True, help="Also install pre-push hook for auto-flush")
def install_hook(global_hook: bool, force: bool, with_pre_push: bool) -> None:
    """Install the jurati post-commit hook for ambient capture."""
    import subprocess

    hook_content = (
        "#!/bin/sh\n"
        "# Jurati post-commit hook — captures jurati: commits\n"
        "MESSAGE=$(git log -1 --format=%B)\n"
        "COMMIT=$(git rev-parse HEAD)\n"
        "AUTHOR=$(git config user.email)\n"
        'jurati capture --message "$MESSAGE" --commit "$COMMIT"'
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
            "# Jurati pre-push hook — flushes pending captures before push\n"
            "jurati flush 2>/dev/null || true\n"
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


@main.command()
@click.option("--message", "-m", required=True, help="Commit message to process")
@click.option("--commit", default="unknown", help="Source commit SHA")
@click.option("--author", default="unknown", help="Source commit author email")
@click.option("--repo-slug", default=None, help="Source repo slug (defaults to current dir name)")
def capture(message: str, commit: str, author: str, repo_slug: str | None) -> None:
    """Process a commit message through the jurati capture pipeline."""
    from jurati.capture.extract import parse_commit_message

    parsed = parse_commit_message(message)
    if parsed is None:
        click.echo("No jurati: prefix found — nothing to capture.")
        return

    if repo_slug is None:
        repo_slug = Path.cwd().name

    click.echo(
        f'[jurati] detected: "{parsed.title}" (type={parsed.entry_type}, level={parsed.level})'
    )


@main.command()
@click.argument("message")
@click.option("--expires", default="2h", help="Expiry duration (e.g. 2h, 30m)")
def active(message: str, expires: str) -> None:
    """Broadcast active status without a commit."""
    click.echo(f'[jurati] active: "{message}" (expires in {expires})')
    click.echo("Note: requires JURATI_KNOWLEDGE_REMOTE to be configured.")


@main.command()
def flush() -> None:
    """List pending captures from the offline queue."""
    from jurati.capture.pending import list_pending

    git_dir = Path(".git")
    if not git_dir.exists():
        click.echo("Error: not in a git repository", err=True)
        raise SystemExit(1)

    pending = list_pending(str(git_dir))
    if not pending:
        click.echo("No pending captures.")
        return

    click.echo(f"Found {len(pending)} pending capture(s).")
    for item in pending:
        click.echo(f"  - {item['commit_sha'][:8]}: {item['message'][:60]}")


@main.command("install-claude-md")
@click.option("--repo-path", default=".", help="Path to the repo to install into.")
@click.option(
    "--remote",
    envvar="JURATI_KNOWLEDGE_REMOTE",
    default=None,
    help="Git remote URL for the knowledge repo (added to CLAUDE.md).",
)
def install_claude_md(repo_path: str, remote: str | None) -> None:
    """Install Jurati CLAUDE.md section and .claude/settings.json into a repo."""
    repo = Path(repo_path)
    claude_md = repo / "CLAUDE.md"

    section = _jurati_claude_md_section(remote)

    if claude_md.exists():
        existing = claude_md.read_text()
        updated, action = _upsert_jurati_claude_md_section(existing, section)
        if updated != existing:
            claude_md.write_text(updated)
        if action == "appended":
            click.echo(f"Appended Jurati section to {claude_md}")
        elif action == "updated":
            click.echo(f"Updated Jurati section in {claude_md}")
        else:
            click.echo(f"Jurati section already current in {claude_md}")
    else:
        claude_md.write_text(section + "\n")
        click.echo(f"Created {claude_md}")

    _write_settings_json(repo, remote=remote)


@main.command("search")
@click.argument("query")
def search_cmd(query: str) -> None:
    """Search the knowledge repo from the command line."""
    click.echo(f"Searching for: {query}")
    click.echo("Note: requires JURATI_KNOWLEDGE_REMOTE to be configured.")


def _serve_check() -> None:
    remote = os.environ.get("JURATI_KNOWLEDGE_REMOTE", "")
    cache_dir = os.environ.get("JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati"))
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")
    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")

    if not remote:
        raise click.ClickException(
            "JURATI_KNOWLEDGE_REMOTE is required. Run `jurati mcp-config --remote <url>` "
            "to generate a client config."
        )

    click.echo("Jurati serve preflight")
    click.echo(f"  knowledge remote: {remote}")
    click.echo(f"  cache directory:  {repo_cache_path(remote, cache_dir)}")
    click.echo(f"  main branch:      {main_branch}")
    click.echo(f"  client slug:      {client_slug}")
    click.echo("")
    click.echo("When started, Jurati will:")
    click.echo("  1. clone or reuse the local cache for the knowledge repo")
    click.echo("  2. fetch the source-of-truth branch and active refs")
    click.echo("  3. build an in-memory index from markdown entries")
    click.echo("  4. answer MCP query/read/list/validate/sync calls from that index")
    click.echo("  5. write only when record/propose/expire is explicitly called")
    click.echo("")
    click.echo("Privacy boundary: no query logging, read receipts, absence signals, or telemetry.")


def _discover_remote() -> str | None:
    """Search for knowledge repo URL in standard locations."""
    import re as _re

    remote = os.environ.get("JURATI_KNOWLEDGE_REMOTE", "").strip()
    if remote:
        return remote

    claude_md = Path("CLAUDE.md")
    if claude_md.exists():
        text = claude_md.read_text()
        match = _re.search(r"Knowledge repo:\s*(\S+)", text)
        if match:
            return match.group(1)

    remote_file = Path(".jurati-remote")
    if remote_file.exists():
        return remote_file.read_text().strip()

    settings = Path(".claude") / "settings.json"
    if settings.exists():
        try:
            data = json.loads(settings.read_text())
            for server_cfg in data.get("mcpServers", {}).values():
                val: str | None = server_cfg.get("env", {}).get("JURATI_KNOWLEDGE_REMOTE")
                if val:
                    return val
        except (json.JSONDecodeError, OSError):
            pass

    diagnostics = _mcp_config_diagnostics(Path.cwd(), Path.home())
    for scope in ("project", "user"):
        for definition in diagnostics.definitions:
            if definition.scope == scope and definition.remote:
                return definition.remote

    return None


def _print_doctor(*, check_startup: bool = False) -> bool:
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati"))
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")
    git_path = shutil.which("git")
    gh_path = shutil.which("gh")

    ready = bool(remote and git_path)

    click.echo("Jurati doctor")
    click.echo("")
    click.echo("What Jurati does:")
    click.echo("  - gives humans and AI agents shared, reviewable context")
    click.echo("  - keeps reads local after sync")
    click.echo("  - uses git branches, refs, and PRs for explicit writes")
    click.echo("  - avoids telemetry, read receipts, and participation tracking")
    click.echo("")
    click.echo("Configuration:")
    click.echo(f"  JURATI_KNOWLEDGE_REMOTE: {_status_value(remote)}")
    click.echo(f"  JURATI_CACHE_DIR:        {cache_dir}")
    if remote:
        click.echo(f"  derived cache path:      {repo_cache_path(remote, cache_dir)}")
    click.echo(f"  JURATI_CLIENT_SLUG:      {client_slug}")
    click.echo("")
    click.echo("Local tools:")
    click.echo(f"  git: {_found_value(git_path)}")
    click.echo(f"  gh:  {_found_value(gh_path)} (needed for PR-creating write tools)")
    click.echo("")
    startup = _startup_diagnostics(Path.cwd(), remote=remote or None)
    _print_startup_diagnostics(startup)
    if not startup.startup_contract_present or not startup.read_only_allowed:
        ready = False
    click.echo("")
    mcp_config = _mcp_config_diagnostics(Path.cwd(), Path.home())
    _print_mcp_config_diagnostics(mcp_config, remote=remote)
    if mcp_config.collision_names:
        ready = False
    click.echo("")

    if check_startup:
        startup_probe_ok = _print_startup_probe(remote, cache_dir)
        ready = ready and startup_probe_ok
        click.echo("")

    click.echo(f"Ready for `jurati serve`: {'yes' if ready else 'no'}")

    if not ready:
        click.echo("")
        click.echo("Fast path:")
        click.echo("  1. Run: jurati quickstart ./jurati-knowledge")
        click.echo("  2. Push that repo, then set JURATI_KNOWLEDGE_REMOTE to its URL.")
        click.echo("  3. Run: jurati mcp-config --remote <url>")
        click.echo("  4. Run: jurati install-claude-md --repo-path . --remote <url>")
        click.echo("  5. Run: jurati doctor --check-startup")
        click.echo("  6. Run: jurati serve --check")

    return ready


def _status_value(value: str | None) -> str:
    return value if value else "missing"


def _found_value(path: str | None) -> str:
    return path if path else "missing"


def _startup_diagnostics(repo: Path, *, remote: str | None = None) -> StartupDiagnostics:
    claude_md = repo / "CLAUDE.md"
    settings_file = repo / ".claude" / "settings.json"
    permissions = _settings_permissions(settings_file)
    expected_read_only = _jurati_expected_settings_allowlist(
        remote=remote,
        include_write=False,
    )
    expected_write = _jurati_expected_settings_allowlist(
        remote=remote,
        include_read_only=False,
    )
    missing_read_only = tuple(tool for tool in expected_read_only if tool not in permissions)
    return StartupDiagnostics(
        claude_md_present=claude_md.exists(),
        startup_contract_present=_has_startup_contract(claude_md.read_text())
        if claude_md.exists()
        else False,
        settings_present=settings_file.exists(),
        read_only_allowed=not missing_read_only,
        write_tools_allowed=all(tool in permissions for tool in expected_write),
        missing_read_only_tools=missing_read_only,
    )


def _settings_permissions(settings_file: Path) -> set[str]:
    if not settings_file.exists():
        return set()
    try:
        data = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    permissions = data.get("permissions", {}).get("allow", [])
    if not isinstance(permissions, list):
        return set()
    return {item for item in permissions if isinstance(item, str)}


def _has_startup_contract(content: str) -> bool:
    normalized = content.lower()
    return (
        "jurati" in normalized
        and "sync()" in content
        and "context()" in content
        and "before" in normalized
    )


def _print_startup_diagnostics(diagnostics: StartupDiagnostics) -> None:
    click.echo("Agent startup:")
    click.echo(f"  CLAUDE.md startup contract: {_yes_no(diagnostics.startup_contract_present)}")
    click.echo(f"  .claude/settings.json:       {_yes_no(diagnostics.settings_present)}")
    click.echo(f"  read-only tools auto-approved: {_yes_no(diagnostics.read_only_allowed)}")
    click.echo(f"  write tools auto-approved:     {_yes_no(diagnostics.write_tools_allowed)}")
    if diagnostics.missing_read_only_tools:
        missing = ", ".join(diagnostics.missing_read_only_tools)
        click.echo(f"  missing read-only tools:       {missing}")
    if not diagnostics.startup_contract_present or not diagnostics.read_only_allowed:
        click.echo("  fix: run `jurati install-claude-md --repo-path . --remote <url>`")


def _mcp_config_locations(repo: Path, home: Path) -> tuple[tuple[str, Path], ...]:
    candidates = [
        ("project", repo / ".mcp.json"),
        ("project", repo / ".claude" / "mcp.json"),
        ("project", repo / ".claude" / "settings.json"),
        ("user", home / ".claude" / "mcp.json"),
        ("user", home / ".claude.json"),
    ]
    locations: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for scope, path in candidates:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        locations.append((scope, path))
    return tuple(locations)


def _mcp_config_diagnostics(repo: Path, home: Path) -> MCPConfigDiagnostics:
    definitions: list[MCPServerDefinition] = []
    read_errors: list[str] = []
    for scope, path in _mcp_config_locations(repo, home):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            read_errors.append(f"{path}: {exc}")
            continue
        for name, raw_config in _iter_mcp_servers(data):
            definitions.append(_mcp_definition(name, raw_config, scope=scope, path=path))

    collision_names = tuple(
        sorted(
            name
            for name in {definition.name for definition in definitions}
            if sum(1 for definition in definitions if definition.name == name) > 1
        )
    )
    return MCPConfigDiagnostics(
        definitions=tuple(definitions),
        read_errors=tuple(read_errors),
        collision_names=collision_names,
    )


def _iter_mcp_servers(value: object) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, dict):
        servers = value.get("mcpServers")
        if isinstance(servers, dict):
            for name, config in servers.items():
                if isinstance(name, str):
                    found.append((name, config))
        for nested in value.values():
            found.extend(_iter_mcp_servers(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_mcp_servers(nested))
    return found


def _mcp_definition(
    name: str, raw_config: object, *, scope: str, path: Path
) -> MCPServerDefinition:
    command: str | None = None
    args: tuple[str, ...] = ()
    remote: str | None = None
    if isinstance(raw_config, dict):
        raw_command = raw_config.get("command")
        if isinstance(raw_command, str):
            command = raw_command
        raw_args = raw_config.get("args")
        if isinstance(raw_args, list):
            args = tuple(item for item in raw_args if isinstance(item, str))
        raw_env = raw_config.get("env")
        if isinstance(raw_env, dict):
            raw_remote = raw_env.get("JURATI_KNOWLEDGE_REMOTE")
            if isinstance(raw_remote, str) and raw_remote:
                remote = raw_remote
    return MCPServerDefinition(
        name=name,
        scope=scope,
        path=path,
        command=command,
        args=args,
        remote=remote,
    )


def _print_mcp_config_diagnostics(diagnostics: MCPConfigDiagnostics, *, remote: str) -> None:
    click.echo("MCP config:")
    if remote:
        click.echo(f"  expected server name: {_mcp_server_name(remote)}")
    if not diagnostics.definitions:
        click.echo("  server definitions found: none")
    else:
        click.echo(f"  server definitions found: {len(diagnostics.definitions)}")
        for definition in diagnostics.definitions:
            click.echo(
                f"  - {definition.name} ({definition.scope}) at {_display_path(definition.path)}"
            )

    if diagnostics.read_errors:
        click.echo("  unreadable config files:")
        for error in diagnostics.read_errors:
            click.echo(f"    - {error}")

    if diagnostics.collision_names:
        click.echo("  collision risk: duplicate MCP server names detected")
        for name in diagnostics.collision_names:
            click.echo(f"    - {name}")
        click.echo("  fix: keep one definition for each server name.")
        click.echo(
            "       For Claude Code, remove a legacy user entry with "
            "`claude mcp remove <name> -s user`,"
        )
        click.echo(
            "       or regenerate project config with "
            "`jurati mcp-config --remote <url> --write-project`."
        )

    legacy = [definition for definition in diagnostics.definitions if definition.name == "jurati"]
    if legacy and not diagnostics.collision_names:
        click.echo("  note: legacy server name 'jurati' found; hash-based names avoid collisions.")


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        relative = path.expanduser().resolve().relative_to(home.expanduser().resolve())
    except ValueError:
        return str(path)
    return f"~/{relative.as_posix()}"


def _print_startup_probe(remote: str, cache_dir: str) -> bool:
    click.echo("Startup probe:")
    if not remote:
        click.echo("  sync():    skipped (missing JURATI_KNOWLEDGE_REMOTE)")
        click.echo("  context(): skipped (missing JURATI_KNOWLEDGE_REMOTE)")
        return False

    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")
    active_ref_prefix = os.environ.get("JURATI_ACTIVE_REF_PREFIX", "jurati/active")
    active_refs_enabled = os.environ.get("JURATI_ACTIVE_REFS_ENABLED", "").lower() == "true"

    try:
        repo_path = ensure_repo(remote, cache_dir)
        fetch_all(
            repo_path,
            main_branch,
            active_ref_prefix,
            active_refs_enabled=active_refs_enabled,
        )
        index = load_index_from_repo(
            repo_path,
            main_branch,
            active_ref_prefix,
            active_refs_enabled=active_refs_enabled,
        )
    except Exception as exc:
        click.echo(f"  sync():    failed ({exc})")
        click.echo("  context(): skipped because sync failed")
        return False

    summary = _startup_context_summary(index, datetime.now(UTC))
    click.echo(f"  sync():    ok ({len(index.entries)} entries indexed)")
    click.echo(
        "  context(): ok "
        f"({summary['active']} active, {summary['recent']} recent entries available)"
    )
    return True


def _startup_context_summary(index: Index, now: datetime) -> dict[str, int]:
    recent_cutoff = now - timedelta(days=7)
    active = 0
    recent = 0
    for entry in index.entries.values():
        fm = entry.frontmatter
        if fm.sensitivity == Sensitivity.RESTRICTED:
            continue
        if fm.type == EntryType.ACTIVE and not is_expired(entry, now):
            active += 1
        if (
            fm.type != EntryType.ACTIVE
            and fm.updated_at >= recent_cutoff
            and fm.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
        ):
            recent += 1
    return {"active": active, "recent": min(recent, 15)}


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _mcp_server_name(remote_url: str) -> str:
    url_hash = hashlib.sha256(remote_url.encode()).hexdigest()[:8]
    return f"jurati-{url_hash}"


def _mcp_config_payload(remote: str, client_slug: str, command_name: str) -> dict[str, object]:
    return {
        "mcpServers": {
            _mcp_server_name(remote): {
                "command": command_name,
                "args": ["serve"],
                "env": {
                    "JURATI_KNOWLEDGE_REMOTE": remote,
                    "JURATI_CLIENT_SLUG": client_slug,
                },
            }
        }
    }


def _mcp_config_json(remote: str, client_slug: str, command_name: str) -> str:
    config = _mcp_config_payload(remote, client_slug, command_name)
    return json.dumps(config, indent=2)


def _write_project_mcp_config(path: Path, payload: dict[str, object]) -> str:
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"Cannot update {path}: invalid JSON: {exc}") from exc
        if not isinstance(existing, dict):
            raise click.ClickException(f"Cannot update {path}: top-level JSON must be an object.")
    else:
        existing = {}

    raw_payload_servers = payload.get("mcpServers")
    if not isinstance(raw_payload_servers, dict) or len(raw_payload_servers) != 1:
        raise click.ClickException("Internal error: generated MCP config is invalid.")
    server_name, server_config = next(iter(raw_payload_servers.items()))
    if not isinstance(server_name, str) or not isinstance(server_config, dict):
        raise click.ClickException("Internal error: generated MCP server config is invalid.")

    raw_existing_servers = existing.setdefault("mcpServers", {})
    if not isinstance(raw_existing_servers, dict):
        raise click.ClickException(f"Cannot update {path}: mcpServers must be an object.")
    raw_existing_servers[server_name] = server_config
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return server_name


def _init_scaffold(root: Path, *, examples: bool, pack: str = "generic") -> list[Path]:
    created: list[Path] = []

    for directory in SCAFFOLD_DIRS:
        path = root / directory
        if not path.exists():
            created.append(path)
        path.mkdir(parents=True, exist_ok=True)

    if _write_if_missing(root / ".jurati" / "config.yaml", DEFAULT_CONFIG):
        created.append(root / ".jurati" / "config.yaml")

    if examples:
        starter_files = _starter_files(root, pack)
        for path, content in starter_files.items():
            if _write_if_missing(path, content):
                created.append(path)

    return created


def _starter_files(root: Path, pack: str) -> dict[Path, str]:
    if pack not in STARTER_PACKS:
        raise click.ClickException(f"Unknown starter pack: {pack}")

    starter_files = {
        root / "README.md": STARTER_README,
        root / "projects" / "first-shared-context.md": STARTER_PROJECT,
        root / "workflows" / "daily-shared-context-loop.md": STARTER_WORKFLOW,
    }
    starter_files.update(
        {root / relative_path: content for relative_path, content in STARTER_PACKS[pack].items()}
    )
    return starter_files


def _validate_knowledge_repo(root: Path) -> tuple[int, list[str]]:
    root = root.resolve()
    errors: list[str] = []
    seen_ids: dict[str, str] = {}
    index = Index()
    entry_count = 0

    for directory in TYPE_DIRS.values():
        entry_dir = root / directory
        if not entry_dir.exists():
            continue

        for path in sorted(entry_dir.glob("*.md")):
            relative_path = path.relative_to(root).as_posix()
            try:
                post = frontmatter.load(path)
                entry = parse_entry(
                    relative_path,
                    dict(post.metadata),
                    post.content,
                )
            except Exception as exc:
                errors.append(f"{relative_path}: parse error: {exc}")
                continue

            entry_count += 1
            entry_id = entry.frontmatter.id

            if entry_id in seen_ids:
                errors.append(
                    f"{relative_path}: duplicate id {entry_id!r} "
                    f"also appears in {seen_ids[entry_id]}"
                )
            else:
                seen_ids[entry_id] = relative_path
                index.add(entry)

            for error in validate_entry(entry):
                errors.append(f"{relative_path}: {error}")

    errors.extend(validate_entry_links(index))
    return entry_count, errors


def _print_import_plan(plan: ImportPlan, repo_path: Path, *, dry_run: bool) -> None:
    click.echo("Context import dry run" if dry_run else "Context import plan")
    click.echo(f"Bundle: {plan.bundle_name}")
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


def _mcp_tool_permission(server_name: str, tool_name: str) -> str:
    return f"mcp__{server_name}__{tool_name}"


def _jurati_settings_allowlist(
    *,
    remote: str | None = None,
    include_read_only: bool = True,
    include_write: bool = True,
) -> list[str]:
    server_names = [DEFAULT_MCP_SERVER_NAME]
    if remote:
        hash_server_name = _mcp_server_name(remote)
        if hash_server_name not in server_names:
            server_names.append(hash_server_name)

    tool_names: list[str] = []
    if include_read_only:
        tool_names.extend(READ_ONLY_MCP_TOOL_NAMES)
    if include_write:
        tool_names.extend(WRITE_MCP_TOOL_NAMES)

    return [
        _mcp_tool_permission(server_name, tool_name)
        for server_name in server_names
        for tool_name in tool_names
    ]


def _jurati_expected_settings_allowlist(
    *,
    remote: str | None = None,
    include_read_only: bool = True,
    include_write: bool = True,
) -> list[str]:
    server_name = _mcp_server_name(remote) if remote else DEFAULT_MCP_SERVER_NAME
    tool_names: list[str] = []
    if include_read_only:
        tool_names.extend(READ_ONLY_MCP_TOOL_NAMES)
    if include_write:
        tool_names.extend(WRITE_MCP_TOOL_NAMES)
    return [_mcp_tool_permission(server_name, tool_name) for tool_name in tool_names]


def _write_settings_json(repo: Path, *, remote: str | None = None) -> None:
    settings_dir = repo / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"

    data = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    for tool in _jurati_settings_allowlist(remote=remote):
        if tool not in allow:
            allow.append(tool)

    settings_file.write_text(json.dumps(data, indent=2) + "\n")
    click.echo(f"Updated {settings_file}")


def _upsert_jurati_claude_md_section(existing: str, section: str) -> tuple[str, str]:
    heading = JURATI_CLAUDE_SECTION_HEADING
    start = existing.find(heading)

    if start == -1:
        if existing.strip():
            return existing.rstrip() + "\n\n" + section + "\n", "appended"
        return section + "\n", "appended"

    next_section = existing.find("\n## ", start + len(heading))
    end = next_section if next_section != -1 else len(existing)
    current_section = existing[start:end].strip()
    if current_section == section.strip():
        return (existing if existing.endswith("\n") else existing + "\n"), "current"

    prefix = existing[:start].rstrip()
    suffix = existing[end:].lstrip("\n")
    parts = [part for part in (prefix, section, suffix.rstrip()) if part]
    return "\n\n".join(parts) + "\n", "updated"


def _jurati_claude_md_section(remote: str | None = None) -> str:
    lines = [
        JURATI_CLAUDE_SECTION_HEADING,
        "",
        "This project uses [Jurati](https://github.com/ostinato-forge/jurati)"
        " for cross-agent coordination.",
    ]
    if remote:
        lines.append("")
        lines.append(f"Knowledge repo: {remote}")
    lines.extend(
        [
            "",
            "### Startup contract",
            "",
            "**Before reading files, checking git state, or making edits, run the"
            " Jurati startup sequence.**",
            "",
            "1. Call `sync()` silently so the local index is fresh.",
            "2. Call `context(repo=<current repo>, goal=<user request>)`.",
            "3. Summarize only relevant decisions, active work, and coordination"
            " blockers in 2-3 sentences for the developer.",
            "4. Use `query(topic=...)` when the startup context points at a specific"
            " decision, workflow, or project you need to inspect.",
            "",
            "Local git branches, diffs, and logs are useful after this sequence,"
            " but they are not a substitute for Jurati context.",
            "",
            "### Tool quick-reference",
            "",
            "| Tool | When to use |",
            "|------|-------------|",
            "| `sync()` | First, silently, before context(). |",
            "| `context()` | Second, before local repo exploration. Pass `repo` and `goal`. |",
            "| `query(topic=...)` | Deep-dive on a specific topic after context(). |",
            "| `record(type, title, content)` |"
            " Capture a status update, in-progress work, or breaking change. |",
            "| `propose(type, title, content)` |"
            " Record a team decision or workflow that needs review. |",
            "",
            "### Normal request mapping",
            "",
            '- "Save this handoff for the next agent." -> `record(type="active", ...)`',
            '- "Capture this project update." -> `record(type="project", ...)`',
            '- "Record this as a team decision." -> `propose(type="decision", ...)`',
            "",
            "The developer should not need to know `record()` versus"
            " `propose()`. Translate the request for them.",
            "",
            "### Rules",
            "",
            "- **Never expose Jurati internals to the developer.**"
            " No entry IDs, ref paths, branch names, expiry dates,"
            " or lifecycle instructions. Never say the word 'Jurati'"
            " when confirming actions — the developer doesn't need to"
            " know which system stored the knowledge.",
            "- **Never ask the developer to manage the knowledge repo.**"
            ' Don\'t say "merge PR #X" or "run sync."',
            "- **Confirm actions in one sentence focused on the work.**"
            ' Say "Recorded the token format decision" — not'
            ' "recording to Jurati," "saving to the knowledge repo,"'
            ' or "other agents will see this." Never reference agents,'
            " coordination mechanics, or visibility plumbing.",
            "- **State coordination plainly.** If someone's PR blocks this work, say so directly.",
            "",
            "### Good developer-facing confirmations",
            "",
            '- "Recorded the token format decision."',
            '- "Saved the handoff for review."',
            '- "Cleared the stale handoff."',
            "",
            "Do not add entry IDs, branch names, ref paths, PR numbers,"
            " sync instructions, or expiry details to these confirmations"
            " unless the developer explicitly asks for debugging details.",
        ]
    )
    return "\n".join(lines)
