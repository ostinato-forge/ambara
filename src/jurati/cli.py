"""CLI entry point: jurati serve, jurati init, jurati validate."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import frontmatter

from jurati import __version__
from jurati.cli_install import (
    DEFAULT_MCP_SERVER_NAME,
    _has_startup_contract,
    _install_claude_md,
    _jurati_expected_settings_allowlist,
    _mcp_config_json,
    _mcp_config_payload,
    _mcp_server_name,
    _write_project_mcp_config,
    _write_settings_json,
)
from jurati.core.graph import validate_entry_links
from jurati.core.index import Index, parse_entry
from jurati.core.paths import TYPE_DIRS
from jurati.core.schema import EntryStatus, EntryType, EscalationLevel, Sensitivity, Visibility
from jurati.core.scope_policy import ScopeMutePolicy, filter_index, scope_policy_summary
from jurati.core.validate import is_expired, validate_entry
from jurati.git.config import MAX_ACTIVE_REF_TTL_HOURS
from jurati.git.import_context import materialize_context_import
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo, repo_cache_path
from jurati.import_context import (
    ContextPackError,
    ImportPlan,
    default_import_branch,
    plan_context_import,
    plan_markdown_import,
)
from jurati.read_model.sqlite import (
    default_db_path,
    query_read_model,
    rebuild_read_model,
)
from jurati.static_html import generate_static_html

SCAFFOLD_DIRS = [
    "principles",
    "decisions",
    "workflows",
    "projects",
    "active",
    "archive",
    ".jurati",
]

PROJECT_TEAM_CONFIG = Path(".jurati") / "config.yaml"


@dataclass(frozen=True)
class StartupDiagnostics:
    claude_md_present: bool
    startup_contract_present: bool
    settings_present: bool
    read_only_allowed: bool
    write_tools_allowed: bool
    missing_read_only_tools: tuple[str, ...]


@dataclass(frozen=True)
class AuditDiagnostics:
    reviewable_git_context: bool
    signed_commits: bool
    append_only_events: bool
    complete_lifecycle_events: bool
    active_refs_audit_safe: bool
    authenticated_identity: bool
    host_protection_verified: bool
    blockers: tuple[str, ...]


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


@dataclass(frozen=True)
class ProjectTeamConfig:
    path: Path
    present: bool
    read_error: str | None
    knowledge_remote: str | None
    enabled: bool | None
    muted_scopes: ScopeMutePolicy
    active_refs_enabled: bool | None
    active_ref_ttl_hours: int | None


DEFAULT_CONFIG = """\
# Config schema version. Entry frontmatter has its own schema_version.
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

STARTER_TIMESTAMP = "__JURATI_STARTER_TIMESTAMP__"


def _starter_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
@click.version_option(__version__, prog_name="jurati")
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
@click.option(
    "--mode",
    type=click.Choice(["adr", "rfc", "docs", "obsidian"]),
    default="adr",
    show_default=True,
    help="How to map source Markdown into Jurati entries.",
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


@main.command()
@click.option(
    "--remote",
    envvar="JURATI_KNOWLEDGE_REMOTE",
    help="Git remote URL for the team knowledge repo. Prompted when omitted.",
)
@click.option(
    "--knowledge-repo",
    default="./jurati-knowledge",
    show_default=True,
    help="Local path for the knowledge repo scaffold.",
)
@click.option(
    "--project-repo",
    default=".",
    show_default=True,
    help="Project repo to connect to Jurati.",
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
    help="Starter pack to add when examples are enabled.",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Accept defaults for optional prompts.",
)
@click.option(
    "--local",
    is_flag=True,
    help="Local-only setup without a remote. Handoffs enabled by default.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    help="Install at user level (~/.claude.json, ~/.claude/CLAUDE.md).",
)
def onboard(
    remote: str | None,
    knowledge_repo: str,
    project_repo: str,
    client_slug: str,
    command_name: str,
    examples: bool,
    pack: str,
    yes: bool,
    local: bool,
    is_global: bool,
) -> None:
    """Create local knowledge and project wiring in one guided run."""
    click.echo("Jurati onboarding")
    click.echo("")

    local_mode = local
    if not remote and not local_mode and not is_global:
        if yes:
            local_mode = True
        else:
            remote = click.prompt(
                "Knowledge repo remote URL (leave empty for local-only mode)",
                default="",
            )
            remote = remote.strip()
            if not remote:
                local_mode = True

    if not local_mode and not remote:
        remote = click.prompt("Knowledge repo remote URL")
        remote = remote.strip()
        if not remote:
            raise click.ClickException("Knowledge repo remote URL is required.")

    if not yes and not is_global and not local_mode:
        knowledge_repo = click.prompt("Knowledge repo path", default=knowledge_repo)
        project_repo = click.prompt("Project repo path", default=project_repo)
        if examples:
            pack = click.prompt(
                "Starter pack",
                default=pack,
                type=click.Choice(sorted(STARTER_PACKS)),
            )

    root = Path(knowledge_repo)

    if not is_global:
        project = Path(project_repo)
        if not project.exists() or not project.is_dir():
            raise click.ClickException(f"Project repo path does not exist: {project}")

    created = _init_scaffold(root, examples=examples, pack=pack)

    if local_mode:
        import subprocess

        root_resolved = root.resolve()
        if not (root_resolved / ".git").exists():
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=root_resolved,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "add", "."],
                cwd=root_resolved,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initialize knowledge repo"],
                cwd=root_resolved,
                check=True,
                capture_output=True,
            )
        remote = str(root_resolved)

    _write_settings_json(root, remote=remote)
    entry_count, errors = _validate_knowledge_repo(root)
    if errors:
        click.echo(f"Validation found {len(errors)} error(s) in {entry_count} entries:")
        for err in errors:
            click.echo(f"  - {err}")
        raise click.ClickException("Fix knowledge repo validation errors before continuing.")

    click.echo("")
    if created:
        click.echo(f"Created knowledge repo scaffold at {root}")
    else:
        click.echo(f"Knowledge repo scaffold already exists at {root}")
    click.echo(f"Validated knowledge repo: {entry_count} entries valid.")
    if examples:
        click.echo(f"Starter pack: {pack}")

    assert remote is not None
    if is_global:
        payload = _mcp_config_payload(remote, client_slug, command_name)
        home = Path.home()
        claude_dir = home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        _install_claude_md(claude_dir, remote, global_install=True)
        _write_settings_json(home, remote=remote)

        claude_json = home / ".claude.json"
        server_name = _write_project_mcp_config(claude_json, payload)
        click.echo(f"Updated {claude_json} with MCP server {server_name!r}.")

        click.echo("")
        click.echo("Global onboarding complete.")
        click.echo("")
        click.echo("What changed:")
        click.echo(f"  - knowledge repo scaffold: {root}")
        click.echo(f"  - agent instructions:       {claude_dir / 'CLAUDE.md'}")
        click.echo(f"  - tool permissions:          {claude_dir / 'settings.json'}")
        click.echo(f"  - MCP server config:         {claude_json}")
        click.echo("")
        click.echo("Jurati is now available in every Claude Code session.")
        click.echo("Restart any running sessions for the changes to take effect.")
    else:
        project = Path(project_repo)
        _install_claude_md(project, remote)
        _write_project_team_config(project, remote=remote, active_refs_enabled=True)
        project_config = _read_project_team_config(project)
        if project_config.read_error:
            raise click.ClickException(
                f"Cannot read project team config: {project_config.read_error}"
            )
        payload = _mcp_config_payload(
            remote,
            client_slug,
            command_name,
            policy_env=_project_active_ref_env(project_config),
        )
        server_name = _write_project_mcp_config(project / ".mcp.json", payload)
        click.echo(f"Updated {project / '.mcp.json'} with MCP server {server_name!r}.")

        click.echo("")
        if local_mode:
            click.echo("Local onboarding complete. Handoffs are enabled.")
        else:
            click.echo("Onboarding complete. Handoffs are enabled.")
        click.echo("")
        click.echo("What changed:")
        click.echo(f"  - knowledge repo:       {root}")
        click.echo(f"  - agent instructions:   {project / 'CLAUDE.md'}")
        click.echo(f"  - project config:       {project / '.jurati' / 'config.yaml'}")
        click.echo(f"  - tool permissions:     {project / '.claude' / 'settings.json'}")
        click.echo(f"  - MCP server config:    {project / '.mcp.json'}")
        click.echo("")
        if local_mode:
            click.echo("Next steps:")
            click.echo("  1. Restart your coding agent in this project.")
            click.echo('  2. Say "save where I left off" to test a handoff.')
            click.echo("  3. Start a new session to see it picked up automatically.")
            click.echo("")
            click.echo("To share with a team later, push the knowledge repo to a remote:")
            click.echo(f"  cd {root}")
            click.echo("  git remote add origin <your-remote-url>")
            click.echo("  git push -u origin main")
        else:
            click.echo("Next steps:")
            click.echo("  1. Push the knowledge repo if it is new:")
            click.echo(f"     cd {root}")
            click.echo("     git init -b main")
            click.echo('     git add . && git commit -m "docs: initialize jurati knowledge repo"')
            click.echo(f"     git remote add origin {remote}")
            click.echo("     git push -u origin main")
            click.echo("  2. Restart your coding agent in the project repo.")
            click.echo("  3. Verify the setup:")
            click.echo("     jurati doctor --check-startup")


@main.command("mcp-config")
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
    "--write-project",
    is_flag=True,
    help="Write or update .mcp.json in the current project with a hash-based server name.",
)
@click.option(
    "--write-global",
    is_flag=True,
    help="Write or update ~/.claude.json with the MCP server config (user-level).",
)
def mcp_config(
    remote: str | None,
    client_slug: str,
    command_name: str,
    write_project: bool,
    write_global: bool,
) -> None:
    """Print or write a collision-resistant MCP config block."""
    project_config = _read_project_team_config(Path.cwd()) if write_project else None
    if not remote and project_config is not None:
        if project_config.read_error:
            raise click.ClickException(
                f"Cannot read project team config: {project_config.read_error}"
            )
        remote = project_config.knowledge_remote
    if not remote:
        raise click.ClickException(
            "JURATI_KNOWLEDGE_REMOTE is required. Pass --remote or set "
            "knowledge_remote in .jurati/config.yaml for --write-project."
        )

    if write_global:
        payload = _mcp_config_payload(remote, client_slug, command_name)
        target = Path.home() / ".claude.json"
        server_name = _write_project_mcp_config(target, payload)
        click.echo(f"Updated {target} with MCP server {server_name!r}.")
        return
    if write_project:
        _write_project_team_config(Path.cwd(), remote=remote)
        project_config = _read_project_team_config(Path.cwd())
        if project_config.read_error:
            raise click.ClickException(
                f"Cannot read project team config: {project_config.read_error}"
            )
        payload = _mcp_config_payload(
            remote,
            client_slug,
            command_name,
            policy_env=_project_active_ref_env(project_config),
        )
        server_name = _write_project_mcp_config(Path(".mcp.json"), payload)
        click.echo(f"Updated .mcp.json with MCP server {server_name!r}.")
        click.echo("Next: run `jurati doctor` to check for duplicate server definitions.")
        return

    payload = _mcp_config_payload(remote, client_slug, command_name)
    click.echo(json.dumps(payload, indent=2))


@main.command("disable")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Project repo to disable Jurati in.",
)
def disable_cmd(repo_path: str) -> None:
    """Disable Jurati for a project without contacting the knowledge repo."""
    repo = Path(repo_path)
    config_path = _set_project_enabled(repo, enabled=False)
    updated_servers = _set_project_mcp_disabled(repo, disabled=True)
    click.echo(f"Disabled Jurati for {repo}.")
    click.echo(f"Updated {config_path}.")
    if updated_servers:
        click.echo(f"Marked {updated_servers} project MCP server(s) disabled.")
    else:
        click.echo("No project MCP server needed updating.")
    click.echo("Agents should treat this as intentional local-only work, not a sync failure.")


@main.command("enable")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Project repo to enable Jurati in.",
)
@click.option(
    "--remote",
    envvar="JURATI_KNOWLEDGE_REMOTE",
    default=None,
    help="Knowledge repo remote to store when enabling a project with no saved remote.",
)
def enable_cmd(repo_path: str, remote: str | None) -> None:
    """Re-enable Jurati for a project."""
    repo = Path(repo_path)
    config = _read_project_team_config(repo)
    if config.read_error:
        raise click.ClickException(f"Cannot read project team config: {config.read_error}")

    saved_remote = remote or config.knowledge_remote
    if not saved_remote:
        raise click.ClickException(
            "Cannot enable Jurati without a knowledge repo remote. Pass --remote."
        )

    config_path = _set_project_enabled(repo, enabled=True, remote=saved_remote)
    updated_servers = _set_project_mcp_disabled(repo, disabled=False)
    click.echo(f"Enabled Jurati for {repo}.")
    click.echo(f"Updated {config_path}.")
    if updated_servers:
        click.echo(f"Marked {updated_servers} project MCP server(s) enabled.")
    else:
        click.echo("No project MCP server needed updating.")
    click.echo("Restart the MCP client if it was already running.")


@main.command("mute-scope")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Project repo to update.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to mute.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to mute.")
@click.option(
    "--signal-source",
    "signal_sources",
    multiple=True,
    help="Coordination signal source/provider to mute.",
)
@click.option("--tag", "tags", multiple=True, help="Entry tag or signal label to mute.")
def mute_scope_cmd(
    repo_path: str,
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    signal_sources: tuple[str, ...],
    tags: tuple[str, ...],
) -> None:
    """Mute local project/repo/signal/tag scopes without deleting knowledge."""
    policy = _scope_policy_from_cli(
        projects=projects,
        repos=repos,
        signal_sources=signal_sources,
        tags=tags,
    )
    if policy.is_empty():
        raise click.ClickException(
            "Pass at least one scope: --project, --repo, --signal-source, or --tag."
        )

    repo = Path(repo_path)
    config_path, updated = _update_project_muted_scopes(repo, policy, remove=False)
    click.echo(f"Muted Jurati scope(s) for {repo}.")
    click.echo(f"Updated {config_path}.")
    _print_muted_scope_summary(updated, prefix="  ")


@main.command("unmute-scope")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Project repo to update.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to unmute.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to unmute.")
@click.option(
    "--signal-source",
    "signal_sources",
    multiple=True,
    help="Coordination signal source/provider to unmute.",
)
@click.option("--tag", "tags", multiple=True, help="Entry tag or signal label to unmute.")
def unmute_scope_cmd(
    repo_path: str,
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    signal_sources: tuple[str, ...],
    tags: tuple[str, ...],
) -> None:
    """Unmute local project/repo/signal/tag scopes."""
    policy = _scope_policy_from_cli(
        projects=projects,
        repos=repos,
        signal_sources=signal_sources,
        tags=tags,
    )
    if policy.is_empty():
        raise click.ClickException(
            "Pass at least one scope: --project, --repo, --signal-source, or --tag."
        )

    repo = Path(repo_path)
    config_path, updated = _update_project_muted_scopes(repo, policy, remove=True)
    click.echo(f"Unmuted Jurati scope(s) for {repo}.")
    click.echo(f"Updated {config_path}.")
    _print_muted_scope_summary(updated, prefix="  ")


@main.command("retire-scope")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Knowledge repo checkout to update.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to retire.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to retire.")
@click.option("--tag", "tags", multiple=True, help="Entry tag to retire.")
@click.option("--branch", default=None, help="Review branch name to create.")
@click.option("--dry-run", is_flag=True, help="Print matching entries without writing.")
def retire_scope_cmd(
    repo_path: str,
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    branch: str | None,
    dry_run: bool,
) -> None:
    """Retire matching knowledge on a review branch without rewriting history."""
    from jurati.git.lifecycle import (
        collect_retire_scope_matches,
        default_retire_scope_branch,
        materialize_retire_scope,
    )

    policy = _scope_policy_from_cli(projects=projects, repos=repos, tags=tags)
    if policy.is_empty():
        raise click.ClickException("Pass at least one scope: --project, --repo, or --tag.")

    now = datetime.now(UTC)
    repo = Path(repo_path)
    try:
        matches = collect_retire_scope_matches(str(repo), policy)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not matches:
        click.echo("No active entries matched the requested scope.")
        return

    click.echo(f"Matched {len(matches)} entr{'y' if len(matches) == 1 else 'ies'} to retire:")
    for match in matches:
        click.echo(f"  - {match.entry_id} ({match.entry_type}) {match.path} -> {match.action}")

    if dry_run:
        click.echo("No files written.")
        return

    branch_name = branch or default_retire_scope_branch(now)
    try:
        result = materialize_retire_scope(
            str(repo),
            policy,
            branch=branch_name,
            now=now,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Retired scope on branch {result.branch} ({result.commit[:8]}).")
    click.echo(f"Lifecycle report: {result.report_path}")
    click.echo("A pull request is needed to merge this lifecycle cleanup.")


@main.command("clear")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Knowledge repo checkout to update.",
)
@click.option(
    "--all",
    "all_entries",
    is_flag=True,
    help="Clear all current entries; restricted entries require --include-restricted.",
)
@click.option(
    "--type",
    "entry_types",
    multiple=True,
    type=click.Choice([str(value) for value in EntryType]),
    help="Entry type to clear.",
)
@click.option(
    "--level",
    "levels",
    multiple=True,
    type=click.Choice([str(value) for value in EscalationLevel]),
    help="Escalation level to clear.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to clear.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to clear.")
@click.option("--tag", "tags", multiple=True, help="Entry tag to clear.")
@click.option(
    "--include-restricted",
    is_flag=True,
    help="Include restricted entries in the reviewed cleanup branch.",
)
@click.option("--branch", default=None, help="Review branch name to create.")
@click.option("--dry-run", is_flag=True, help="Print matching entries without writing.")
def clear_cmd(
    repo_path: str,
    all_entries: bool,
    entry_types: tuple[str, ...],
    levels: tuple[str, ...],
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    include_restricted: bool,
    branch: str | None,
    dry_run: bool,
) -> None:
    """Bulk-clear current context on a review branch without deleting history."""
    from jurati.git.lifecycle import (
        ClearEntriesFilter,
        collect_clear_entries_matches,
        default_clear_entries_branch,
        materialize_clear_entries,
    )

    filters = ClearEntriesFilter(
        entry_types=tuple(EntryType(value) for value in entry_types),
        levels=tuple(EscalationLevel(value) for value in levels),
        projects=projects,
        repos=repos,
        tags=tags,
        include_restricted=include_restricted,
    )
    if all_entries and filters.has_selectors():
        raise click.ClickException("Use --all by itself, or omit --all and pass filters.")
    if not all_entries and not filters.has_selectors():
        raise click.ClickException(
            "Pass --all or at least one filter: --type, --level, --project, --repo, or --tag."
        )

    now = datetime.now(UTC)
    repo = Path(repo_path)
    try:
        matches = collect_clear_entries_matches(str(repo), filters)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not matches:
        click.echo("No current entries matched the clear filters.")
        return

    click.echo(f"Matched {len(matches)} entr{'y' if len(matches) == 1 else 'ies'} to clear:")
    for match in matches:
        click.echo(
            f"  - {match.entry_id} ({match.entry_type}/{match.level}, "
            f"{match.sensitivity}) {match.path} -> {match.action}"
        )

    if dry_run:
        click.echo("No files written.")
        return

    branch_name = branch or default_clear_entries_branch(now)
    try:
        result = materialize_clear_entries(
            str(repo),
            filters,
            branch=branch_name,
            now=now,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Cleared context on branch {result.branch} ({result.commit[:8]}).")
    click.echo(f"Lifecycle report: {result.report_path}")
    click.echo("A pull request is needed to merge this lifecycle cleanup.")


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
@click.option(
    "--fix-project-config",
    is_flag=True,
    help="Repair safe project-local Jurati config before running diagnostics.",
)
@click.option(
    "--team",
    is_flag=True,
    help="Report repo-level team readiness from .jurati/config.yaml.",
)
@click.option(
    "--audit",
    is_flag=True,
    help="Report tamper-evidence/SOC2 audit-ledger readiness.",
)
def doctor(
    strict: bool,
    check_startup: bool,
    fix_project_config: bool,
    team: bool,
    audit: bool,
) -> None:
    """Explain Jurati setup and check whether this machine is ready."""
    if fix_project_config:
        ready = _repair_project_config_then_print_doctor(
            check_startup=check_startup,
            team=team,
            audit=audit,
        )
    else:
        ready = _print_doctor(check_startup=check_startup, team=team, audit=audit)
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
    """Generate a JURATI_PRIVACY_SALT value for opaque identity hashing."""
    from jurati.core.privacy import generate_privacy_salt

    click.echo(generate_privacy_salt(num_bytes=num_bytes))


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
    from jurati.capture.pending import save_pending

    parsed = parse_commit_message(message)
    if parsed is None:
        click.echo("No jurati: prefix found — nothing to capture.")
        return

    if repo_slug is None:
        repo_slug = Path.cwd().name

    git_dir = _local_git_dir(Path.cwd())
    try:
        save_pending(str(git_dir), commit, message, author=author, repo_slug=repo_slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f'[jurati] queued: "{parsed.title}" (type={parsed.entry_type}, level={parsed.level})'
    )


@main.command("startup")
@click.option("--repo", default=None, help="Project slug for filtering entries.")
@click.option("--goal", default=None, help="User request for relevance ranking.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "md"]),
    default="json",
    help="Output format (default: json).",
)
@click.option(
    "--output", "-o", "output_path", default=None, help="Write to file instead of stdout."
)
@click.option("--max-entries", default=5, help="Maximum entries to include.")
@click.option(
    "--include-muted",
    is_flag=True,
    help="Include locally muted scopes for historical/manual lookup.",
)
def startup_cmd(
    repo: str | None,
    goal: str | None,
    fmt: str,
    output_path: str | None,
    max_entries: int,
    include_muted: bool,
) -> None:
    """Compile project context to a file or stdout. No MCP server needed."""
    from jurati.cli_render import render_startup_markdown
    from jurati.core.scoring import build_inverted_index
    from jurati.git.config import load_config_from_env
    from jurati.server_read import _build_disabled_startup_v2_payload, build_startup_v2_payload
    from jurati.server_state import SyncHealth

    project_config = _read_project_team_config(Path.cwd())
    if project_config.read_error:
        raise click.ClickException(f"Cannot read project team config: {project_config.read_error}")
    if project_config.enabled is False:
        packet = _build_disabled_startup_v2_payload()
        output = render_startup_markdown(packet) if fmt == "md" else json.dumps(packet, indent=2)
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(output)
            click.echo(f"Wrote {fmt} context to {output_path}", err=True)
        else:
            click.echo(output)
        return

    try:
        config = load_config_from_env()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
        index = load_index_from_repo(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
        if not include_muted:
            index = filter_index(index, config.muted_scopes)
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    now = datetime.now(UTC)
    visible_entries = [
        e for e in index.entries.values() if e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]
    bm25 = build_inverted_index(visible_entries)

    packet = build_startup_v2_payload(
        index,
        now=now,
        sync_health=SyncHealth(last_success=now),
        freshness_warning_seconds=config.context_freshness_warning_seconds,
        stale_after_seconds=config.context_stale_after_seconds,
        repo=repo,
        goal=goal,
        max_entries=max_entries,
        prebuilt_index=bm25,
    )

    output = render_startup_markdown(packet) if fmt == "md" else json.dumps(packet, indent=2)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(output)
        click.echo(f"Wrote {fmt} context to {output_path}", err=True)
    else:
        click.echo(output)


@main.command("record")
@click.option(
    "--type",
    "entry_type",
    required=True,
    type=click.Choice(["active", "project"]),
    help="Entry type (active=L0 short-lived, project=L1 lightweight PR).",
)
@click.option("--title", required=True, help="Entry title.")
@click.option("--content", required=True, help="Entry body text.")
@click.option("--projects", default=None, help="Comma-separated project slugs.")
@click.option("--tags", default=None, help="Comma-separated tags.")
def record_cmd(
    entry_type: str,
    title: str,
    content: str,
    projects: str | None,
    tags: str | None,
) -> None:
    """Record a handoff, status update, or active context. No MCP server needed."""
    from jurati.cli_write import (
        check_content_policy,
        do_active_write,
        do_branch_write,
        gen_entry_id,
    )
    from jurati.core.changes import plan_record
    from jurati.git.config import load_config_from_env

    try:
        config = load_config_from_env()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    parsed_type = EntryType(entry_type)
    project_list = [p.strip() for p in projects.split(",")] if projects else []
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    now = datetime.now(UTC)
    eid = gen_entry_id()

    if parsed_type == EntryType.ACTIVE and not config.active_refs_enabled:
        raise click.ClickException(
            "Active context is disabled by repo policy. "
            "Set JURATI_ACTIVE_REFS_ENABLED=true to opt in."
        )

    check_content_policy(
        source="record",
        title=title,
        content=content,
        entry_type=parsed_type,
        projects=project_list,
        tags=tag_list,
    )

    exp = None
    if parsed_type == EntryType.ACTIVE:
        exp = now + timedelta(hours=config.active_ref_ttl_hours)

    try:
        intent = plan_record(
            parsed_type,
            title,
            content,
            entry_id=eid,
            projects=project_list,
            tags=tag_list,
            now=now,
            expires_at=exp,
            branch_prefix=config.branch_prefix,
            active_ref_prefix=config.active_ref_prefix,
            client=config.client_slug,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        if intent.write_mode == "active_ref":
            sha = do_active_write(repo_path, intent, config.main_branch)
            click.echo(f"Recorded active context: {title}")
        else:
            sha = do_branch_write(repo_path, intent, config.main_branch)
            click.echo(f"Recorded on branch {intent.branch} ({sha[:8]})")
            click.echo("A pull request is needed to merge this entry.")
    except Exception as exc:
        raise click.ClickException(f"Write failed: {exc}") from exc


@main.command("propose")
@click.option(
    "--type",
    "entry_type",
    required=True,
    type=click.Choice(["decision", "workflow", "principle"]),
    help="Entry type for team review.",
)
@click.option("--title", required=True, help="Entry title.")
@click.option("--content", required=True, help="Entry body text.")
@click.option("--projects", default=None, help="Comma-separated project slugs.")
@click.option("--tags", default=None, help="Comma-separated tags.")
def propose_cmd(
    entry_type: str,
    title: str,
    content: str,
    projects: str | None,
    tags: str | None,
) -> None:
    """Propose a project decision or workflow for review. No MCP server needed."""
    from jurati.cli_write import check_content_policy, do_branch_write, gen_entry_id
    from jurati.core.changes import plan_propose
    from jurati.git.config import load_config_from_env

    try:
        config = load_config_from_env()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    parsed_type = EntryType(entry_type)
    project_list = [p.strip() for p in projects.split(",")] if projects else []
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    now = datetime.now(UTC)
    eid = gen_entry_id()

    check_content_policy(
        source="propose",
        title=title,
        content=content,
        entry_type=parsed_type,
        projects=project_list,
        tags=tag_list,
    )

    try:
        intent = plan_propose(
            parsed_type,
            title,
            content,
            entry_id=eid,
            projects=project_list,
            tags=tag_list,
            now=now,
            branch_prefix=config.branch_prefix,
            client=config.client_slug,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        sha = do_branch_write(repo_path, intent, config.main_branch)
        click.echo(f"Proposed on branch {intent.branch} ({sha[:8]})")
        click.echo("A pull request is needed to merge this entry.")
    except Exception as exc:
        raise click.ClickException(f"Write failed: {exc}") from exc


@main.command("query")
@click.argument("topic")
@click.option("--max-results", default=5, help="Maximum results to return.")
@click.option("--include-muted", is_flag=True, help="Include locally muted scopes.")
def query_cmd(topic: str, max_results: int, include_muted: bool) -> None:
    """Search project context by topic. No MCP server needed."""
    from jurati.core.scoring import rank_entries
    from jurati.git.config import load_config_from_env

    try:
        config = load_config_from_env()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
        index = load_index_from_repo(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    if not include_muted:
        index = filter_index(index, config.muted_scopes)
    now = datetime.now(UTC)
    visible = index.list_entries(now=now)
    results = rank_entries(visible, topic, now=now, max_results=max_results)

    if not results:
        click.echo(f"No results for: {topic}")
        return

    for result in results:
        fm = result.entry.frontmatter
        click.echo(f"\n## {fm.title}")
        click.echo(f"**{fm.id}** ({fm.type}) — {fm.status}")
        if result.entry.body.strip():
            body_preview = result.entry.body.strip()[:300]
            if len(result.entry.body.strip()) > 300:
                body_preview += "..."
            click.echo(body_preview)


@main.command("read")
@click.argument("entry_id")
def read_cmd(entry_id: str) -> None:
    """Read a single knowledge entry by ID. No MCP server needed."""
    from jurati.git.config import load_config_from_env

    try:
        config = load_config_from_env()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
        index = load_index_from_repo(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    entry = index.entries.get(entry_id)
    if entry is None:
        raise click.ClickException(f"Entry not found: {entry_id}")

    fm = entry.frontmatter
    click.echo(f"# {fm.title}")
    click.echo(
        f"**ID:** {fm.id}  **Type:** {fm.type}  **Level:** {fm.level}  **Status:** {fm.status}"
    )
    click.echo(f"**Created:** {fm.created_at}  **Updated:** {fm.updated_at}")
    if fm.projects:
        click.echo(f"**Projects:** {', '.join(fm.projects)}")
    if fm.tags:
        click.echo(f"**Tags:** {', '.join(fm.tags)}")
    click.echo("")
    click.echo(entry.body.strip())


@main.command()
@click.argument("message")
@click.option("--expires", default="2h", help="Expiry duration (e.g. 2h, 30m)")
def active(message: str, expires: str) -> None:
    """Broadcast active status without a commit."""
    click.echo(f'[jurati] active: "{message}" (expires in {expires})')
    click.echo("Note: requires JURATI_KNOWLEDGE_REMOTE to be configured.")


@main.command()
@click.option("--dry-run", is_flag=True, help="List pending captures without writing.")
def flush(dry_run: bool) -> None:
    """Flush pending captures from the offline queue."""
    from jurati.capture.pending import list_pending, remove_pending
    from jurati.capture.pipeline import run_capture
    from jurati.git.config import load_config_from_env

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


@main.command("install-claude-md")
@click.option("--repo-path", default=".", help="Path to the repo to install into.")
@click.option(
    "--remote",
    envvar="JURATI_KNOWLEDGE_REMOTE",
    default=None,
    help="Git remote URL for the knowledge repo (added to CLAUDE.md).",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    help="Install to ~/.claude/CLAUDE.md and ~/.claude/settings.json (user-level).",
)
@click.option(
    "--v1",
    "use_v1",
    is_flag=True,
    help="Use the verbose v1 startup template (~1000 tokens instead of ~200).",
)
def install_claude_md(repo_path: str, remote: str | None, is_global: bool, use_v1: bool) -> None:
    """Install Jurati CLAUDE.md section and .claude/settings.json."""
    use_v2 = not use_v1
    if is_global:
        target = Path.home() / ".claude"
        target.mkdir(parents=True, exist_ok=True)
        _install_claude_md(target, remote, global_install=True, use_v2=use_v2)
        _write_settings_json(Path.home(), remote=remote)
    else:
        _install_claude_md(Path(repo_path), remote, use_v2=use_v2)


@main.command("search")
@click.argument("query")
def search_cmd(query: str) -> None:
    """Search the knowledge repo from the command line."""
    click.echo(f"Searching for: {query}")
    click.echo("Note: requires JURATI_KNOWLEDGE_REMOTE to be configured.")


def _serve_check() -> None:
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati"))
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")
    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")
    project_config = _read_project_team_config(Path.cwd())
    disabled = _jurati_disabled(project_config)

    if disabled:
        click.echo("Jurati serve preflight")
        click.echo("  state:           disabled")
        click.echo(f"  config path:     {_display_path(project_config.path)}")
        click.echo(f"  knowledge remote: {_status_value(remote)}")
        click.echo("")
        click.echo("When started, Jurati will:")
        click.echo("  1. skip knowledge repo clone, fetch, and indexing")
        click.echo("  2. report disabled status to MCP status/sync/startup/context calls")
        click.echo("  3. tell agents to proceed from local project context")
        click.echo("")
        click.echo(
            "Privacy boundary: no query logging, read receipts, absence signals, or telemetry."
        )
        return

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

    project_config = _read_project_team_config(Path.cwd())
    if project_config.knowledge_remote:
        return project_config.knowledge_remote

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


def _print_doctor(*, check_startup: bool = False, team: bool = False, audit: bool = False) -> bool:
    project_config = _read_project_team_config(Path.cwd())
    disabled = _jurati_disabled(project_config)
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati"))
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")
    git_path = shutil.which("git")
    gh_path = shutil.which("gh")

    serve_ready = True if disabled else bool(remote and git_path)
    audit_ready: bool | None = None

    click.echo("Jurati doctor")
    click.echo("")
    click.echo("What Jurati does:")
    click.echo("  - gives humans and AI agents shared, reviewable context")
    click.echo("  - keeps reads local after sync")
    click.echo("  - uses git branches, refs, and PRs for explicit writes")
    click.echo("  - avoids telemetry, read receipts, and participation tracking")
    click.echo("")
    click.echo("Configuration:")
    click.echo(f"  Jurati disabled:         {_yes_no(disabled)}")
    click.echo(f"  JURATI_KNOWLEDGE_REMOTE: {_status_value(remote)}")
    click.echo(f"  JURATI_CACHE_DIR:        {cache_dir}")
    if remote:
        click.echo(f"  derived cache path:      {repo_cache_path(remote, cache_dir)}")
    click.echo(f"  JURATI_CLIENT_SLUG:      {client_slug}")
    if disabled:
        click.echo("  disabled behavior:      local-only; no knowledge repo fetch")
    _print_muted_scope_summary(project_config.muted_scopes, prefix="  ")
    click.echo("")
    click.echo("Local tools:")
    click.echo(f"  git: {_found_value(git_path)}")
    click.echo(f"  gh:  {_found_value(gh_path)} (needed for PR-creating write tools)")
    click.echo("")
    startup = _startup_diagnostics(Path.cwd(), remote=remote or None)
    _print_startup_diagnostics(startup, disabled=disabled)
    if not disabled and (not startup.startup_contract_present or not startup.read_only_allowed):
        serve_ready = False
    click.echo("")
    mcp_config = _mcp_config_diagnostics(Path.cwd(), Path.home())
    _print_mcp_config_diagnostics(mcp_config, remote=remote)
    blocking_collision_names = _blocking_mcp_collision_names(mcp_config.collision_names)
    if blocking_collision_names and not disabled:
        serve_ready = False
    click.echo("")

    if audit:
        audit_ready = _print_audit_diagnostics(_audit_diagnostics())
        click.echo("")

    if team:
        if disabled:
            team_ready = _print_disabled_team_readiness(project_config)
        else:
            team_ready = _print_team_readiness(
                Path.cwd(),
                remote=remote,
                startup=startup,
                mcp_config=mcp_config,
                gh_path=gh_path,
            )
        serve_ready = serve_ready and team_ready
        click.echo("")

    if check_startup:
        if disabled:
            startup_probe_ok = _print_disabled_startup_probe()
        else:
            startup_probe_ok = _print_startup_probe(remote, cache_dir)
        serve_ready = serve_ready and startup_probe_ok
        click.echo("")

    click.echo(f"Ready for `jurati serve`: {'yes' if serve_ready else 'no'}")
    if audit_ready is not None:
        click.echo(f"Ready for audit ledger claims: {_yes_no(audit_ready)}")

    if not serve_ready and not disabled:
        click.echo("")
        click.echo("Fast path:")
        click.echo("  1. Run: jurati onboard --remote <url>")
        click.echo("  2. Push the generated knowledge repo if it is new.")
        click.echo("  3. Run: jurati doctor --check-startup")
        click.echo("  4. Restart the MCP client and start a normal task.")

    return serve_ready and (audit_ready if audit_ready is not None else True)


def _repair_project_config_then_print_doctor(
    *, check_startup: bool = False, team: bool = False, audit: bool = False
) -> bool:
    remote = _discover_remote()
    if not remote:
        raise click.ClickException(
            "Cannot repair project config without a knowledge repo remote. "
            "Run `jurati onboard --remote <url>` or set JURATI_KNOWLEDGE_REMOTE."
        )

    project = Path.cwd()
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")

    click.echo("Project config repair")
    click.echo(f"  knowledge remote: {remote}")
    click.echo("")

    _install_claude_md(project, remote)
    _write_project_team_config(project, remote=remote)
    project_config = _read_project_team_config(project)
    if project_config.read_error:
        raise click.ClickException(f"Cannot read project team config: {project_config.read_error}")
    payload = _mcp_config_payload(
        remote,
        client_slug,
        "jurati",
        policy_env=_project_active_ref_env(project_config),
    )
    server_name = _write_project_mcp_config(project / ".mcp.json", payload)
    click.echo(f"Updated {project / '.mcp.json'} with MCP server {server_name!r}.")
    click.echo("")

    return _print_doctor(check_startup=check_startup, team=team, audit=audit)


def _read_project_team_config(repo: Path) -> ProjectTeamConfig:
    path = repo / PROJECT_TEAM_CONFIG
    if not path.exists():
        return ProjectTeamConfig(
            path=path,
            present=False,
            read_error=None,
            knowledge_remote=None,
            enabled=None,
            muted_scopes=ScopeMutePolicy(),
            active_refs_enabled=None,
            active_ref_ttl_hours=None,
        )

    try:
        data = _load_yaml_mapping(path)
    except ValueError as exc:
        return ProjectTeamConfig(
            path=path,
            present=True,
            read_error=str(exc),
            knowledge_remote=None,
            enabled=None,
            muted_scopes=ScopeMutePolicy(),
            active_refs_enabled=None,
            active_ref_ttl_hours=None,
        )

    enabled = _project_enabled_from_config(data)
    muted_scopes = ScopeMutePolicy.from_raw(data.get("muted_scopes"))
    active_refs_enabled = _active_refs_policy_from_config(data)
    try:
        active_ref_ttl_hours = _active_ref_ttl_hours_from_config(data)
    except ValueError as exc:
        return ProjectTeamConfig(
            path=path,
            present=True,
            read_error=str(exc),
            knowledge_remote=_optional_str(data.get("knowledge_remote")),
            enabled=enabled,
            muted_scopes=muted_scopes,
            active_refs_enabled=active_refs_enabled,
            active_ref_ttl_hours=None,
        )

    return ProjectTeamConfig(
        path=path,
        present=True,
        read_error=None,
        knowledge_remote=_optional_str(data.get("knowledge_remote")),
        enabled=enabled,
        muted_scopes=muted_scopes,
        active_refs_enabled=active_refs_enabled,
        active_ref_ttl_hours=active_ref_ttl_hours,
    )


def _write_project_team_config(
    repo: Path, *, remote: str, active_refs_enabled: bool = False
) -> Path:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    data.setdefault("schema_version", 1)
    data.setdefault("enabled", True)
    data["knowledge_remote"] = remote
    if "active_refs_enabled" not in data and "active_refs" not in data:
        data["active_refs_enabled"] = active_refs_enabled
    expiry = data.setdefault("expiry", {})
    if isinstance(expiry, dict):
        expiry.setdefault("active_ttl_hours", 72)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    click.echo(f"Updated {path}.")
    return path


def _set_project_enabled(repo: Path, *, enabled: bool, remote: str | None = None) -> Path:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    data.setdefault("schema_version", 1)
    data["enabled"] = enabled
    if remote is not None:
        data["knowledge_remote"] = remote
    if enabled and not _optional_str(data.get("knowledge_remote")):
        raise click.ClickException(
            "Cannot enable Jurati without a knowledge repo remote. Pass --remote."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    return path


def _set_project_mcp_disabled(repo: Path, *, disabled: bool) -> int:
    path = repo / ".mcp.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Cannot update {path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise click.ClickException(f"Cannot update {path}: top-level JSON must be an object.")

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return 0

    updated = 0
    for name, raw_config in servers.items():
        if not isinstance(name, str) or not isinstance(raw_config, dict):
            continue
        env = raw_config.setdefault("env", {})
        if not isinstance(env, dict):
            continue
        is_jurati = (
            name == DEFAULT_MCP_SERVER_NAME
            or name.startswith(f"{DEFAULT_MCP_SERVER_NAME}-")
            or "JURATI_KNOWLEDGE_REMOTE" in env
            or raw_config.get("command") == "jurati"
        )
        if not is_jurati:
            continue
        if disabled:
            env["JURATI_DISABLED"] = "true"
        else:
            env.pop("JURATI_DISABLED", None)
        updated += 1

    if updated:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def _scope_policy_from_cli(
    *,
    projects: tuple[str, ...] = (),
    repos: tuple[str, ...] = (),
    signal_sources: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
) -> ScopeMutePolicy:
    return ScopeMutePolicy.from_raw(
        {
            "projects": list(projects),
            "repos": list(repos),
            "signal_sources": list(signal_sources),
            "tags": list(tags),
        }
    )


def _update_project_muted_scopes(
    repo: Path, policy: ScopeMutePolicy, *, remove: bool
) -> tuple[Path, ScopeMutePolicy]:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    current = ScopeMutePolicy.from_raw(data.get("muted_scopes"))
    updated = current.without(policy) if remove else current.merge(policy)
    data.setdefault("schema_version", 1)
    if updated.is_empty():
        data.pop("muted_scopes", None)
    else:
        data["muted_scopes"] = updated.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    return path, updated


def _print_muted_scope_summary(policy: ScopeMutePolicy, *, prefix: str = "") -> None:
    if policy.is_empty():
        click.echo(f"{prefix}muted scopes: none")
        return
    summary = scope_policy_summary(policy)
    click.echo(f"{prefix}muted scopes: {summary['total']}")
    for key in ("projects", "repos", "signal_sources", "tags"):
        values = summary[key]
        if values:
            click.echo(f"{prefix}{key}: {', '.join(values)}")


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    try:
        loaded: object = frontmatter.default_handlers.YAMLHandler().load(path.read_text())
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("top-level YAML must be a mapping")
    return {key: value for key, value in loaded.items() if isinstance(key, str)}


def _dump_yaml_mapping(data: dict[str, object]) -> str:
    rendered: str = frontmatter.default_handlers.YAMLHandler().export(data, sort_keys=False)
    return rendered + "\n"


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _active_refs_policy_from_config(data: dict[str, object]) -> bool | None:
    active_refs = data.get("active_refs")
    if isinstance(active_refs, dict):
        enabled = active_refs.get("enabled")
        if isinstance(enabled, bool):
            return enabled
    value = data.get("active_refs_enabled")
    if isinstance(value, bool):
        return value
    expiry = data.get("expiry")
    if isinstance(expiry, dict):
        expiry_value = expiry.get("active_refs_enabled")
        if isinstance(expiry_value, bool):
            return expiry_value
    return None


def _project_enabled_from_config(data: dict[str, object]) -> bool:
    value = data.get("enabled")
    if isinstance(value, bool):
        return value
    disabled = data.get("disabled")
    if isinstance(disabled, bool):
        return not disabled
    return True


def _jurati_disabled(config: ProjectTeamConfig) -> bool:
    return os.environ.get("JURATI_DISABLED", "").lower() == "true" or config.enabled is False


def _active_ref_ttl_hours_from_config(data: dict[str, object]) -> int | None:
    active_refs = data.get("active_refs")
    if isinstance(active_refs, dict):
        ttl = _ttl_hours(active_refs.get("ttl_hours"))
        if ttl is not None:
            return ttl
    expiry = data.get("expiry")
    if isinstance(expiry, dict):
        return _ttl_hours(expiry.get("active_ttl_hours"))
    return None


def _ttl_hours(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        ttl = None
    elif isinstance(value, int):
        ttl = value
    elif isinstance(value, str) and value.strip().isdigit():
        ttl = int(value.strip())
    else:
        ttl = None

    if ttl is None or not 1 <= ttl <= MAX_ACTIVE_REF_TTL_HOURS:
        raise ValueError(
            f"active ref TTL must be an integer between 1 and {MAX_ACTIVE_REF_TTL_HOURS} hours"
        )
    return ttl


def _project_active_ref_env(config: ProjectTeamConfig) -> dict[str, str]:
    env: dict[str, str] = {}
    if config.enabled is False:
        env["JURATI_DISABLED"] = "true"
    if config.active_refs_enabled is not None:
        env["JURATI_ACTIVE_REFS_ENABLED"] = "true" if config.active_refs_enabled else "false"
    if config.active_ref_ttl_hours is not None:
        env["JURATI_ACTIVE_REF_TTL_HOURS"] = str(config.active_ref_ttl_hours)
    return env


def _active_refs_policy_label(value: bool | None) -> str:
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    return "missing"


def _has_project_mcp_config(
    diagnostics: MCPConfigDiagnostics,
    *,
    remote: str,
) -> bool:
    for definition in diagnostics.definitions:
        if definition.scope != "project":
            continue
        if not (
            definition.name == DEFAULT_MCP_SERVER_NAME or definition.name.startswith("jurati-")
        ):
            continue
        if remote and definition.remote != remote:
            continue
        return True
    return False


def _print_team_readiness(
    repo: Path,
    *,
    remote: str,
    startup: StartupDiagnostics,
    mcp_config: MCPConfigDiagnostics,
    gh_path: str | None,
) -> bool:
    config = _read_project_team_config(repo)
    project_mcp_present = _has_project_mcp_config(mcp_config, remote=remote)
    active_policy_known = config.active_refs_enabled is not None
    write_path_available = bool(gh_path) and startup.write_tools_allowed

    team_ready = (
        config.present
        and config.enabled is not False
        and config.read_error is None
        and bool(remote)
        and bool(config.knowledge_remote)
        and project_mcp_present
        and startup.startup_contract_present
        and startup.read_only_allowed
        and active_policy_known
    )

    click.echo("Team readiness:")
    click.echo(f"  repo participation marker: {_yes_no(config.present)}")
    click.echo(f"  config path:               {_display_path(config.path)}")
    if config.read_error:
        click.echo(f"  config error:              {config.read_error}")
    click.echo(f"  Jurati enabled:            {_yes_no(config.enabled is not False)}")
    click.echo(f"  config knowledge remote:   {_status_value(config.knowledge_remote)}")
    click.echo(f"  discovered remote:         {_status_value(remote)}")
    click.echo(f"  project MCP config:        {_yes_no(project_mcp_present)}")
    click.echo(f"  startup contract:          {_yes_no(startup.startup_contract_present)}")
    click.echo(f"  read-only tools:           {_yes_no(startup.read_only_allowed)}")
    click.echo(f"  write path available:      {_yes_no(write_path_available)}")
    active_policy = _active_refs_policy_label(config.active_refs_enabled)
    click.echo(f"  active refs policy:        {active_policy}")
    if config.active_ref_ttl_hours is not None:
        click.echo(f"  active refs TTL:           {config.active_ref_ttl_hours}h")
    _print_muted_scope_summary(config.muted_scopes, prefix="  ")
    click.echo(
        "  privacy boundary:          repo readiness only; no teammate install/presence tracking"
    )
    click.echo(f"  Team ready:                {_yes_no(team_ready)}")
    if not team_ready:
        click.echo(
            "  fix: run `jurati doctor --fix-project-config --team` "
            "after setting the knowledge remote."
        )
    return team_ready


def _print_disabled_team_readiness(config: ProjectTeamConfig) -> bool:
    click.echo("Team readiness:")
    click.echo(f"  repo participation marker: {_yes_no(config.present)}")
    click.echo(f"  config path:               {_display_path(config.path)}")
    if config.read_error:
        click.echo(f"  config error:              {config.read_error}")
        return False
    click.echo("  Jurati enabled:            no")
    _print_muted_scope_summary(config.muted_scopes, prefix="  ")
    click.echo("  Team ready:                skipped; Jurati disabled for this project")
    return True


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


def _print_startup_diagnostics(diagnostics: StartupDiagnostics, *, disabled: bool = False) -> None:
    click.echo("Agent startup:")
    click.echo(f"  CLAUDE.md startup contract: {_yes_no(diagnostics.startup_contract_present)}")
    click.echo(f"  .claude/settings.json:       {_yes_no(diagnostics.settings_present)}")
    click.echo(f"  read-only tools auto-approved: {_yes_no(diagnostics.read_only_allowed)}")
    click.echo(f"  write tools auto-approved:     {_yes_no(diagnostics.write_tools_allowed)}")
    if diagnostics.missing_read_only_tools:
        missing = ", ".join(diagnostics.missing_read_only_tools)
        click.echo(f"  missing read-only tools:       {missing}")
    if disabled:
        click.echo("  disabled state:             agents proceed local-only")
    elif not diagnostics.startup_contract_present or not diagnostics.read_only_allowed:
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


def _blocking_mcp_collision_names(collision_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        name
        for name in collision_names
        if name == DEFAULT_MCP_SERVER_NAME or name.startswith(f"{DEFAULT_MCP_SERVER_NAME}-")
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
        blocking = _blocking_mcp_collision_names(diagnostics.collision_names)
        if blocking:
            click.echo("  fix: keep one Jurati definition for each server name.")
            click.echo(
                "       For Claude Code, remove a legacy user entry with "
                "`claude mcp remove <name> -s user`,"
            )
            click.echo(
                "       or regenerate project config with "
                "`jurati mcp-config --remote <url> --write-project`."
            )
        else:
            click.echo("  note: duplicate non-Jurati servers do not block Jurati startup.")

    legacy = [definition for definition in diagnostics.definitions if definition.name == "jurati"]
    if legacy and not diagnostics.collision_names:
        click.echo("  note: legacy server name 'jurati' found; hash-based names avoid collisions.")


def _audit_diagnostics() -> AuditDiagnostics:
    blockers = (
        "Jurati-created commits are not signed or verified by Jurati.",
        "Lifecycle event files are not append-only, hash-chained, signed, or complete for L0.",
        "L0 active refs can be deleted and are explicitly non-audit context today.",
        "recorded_by/source metadata are informational, not authenticated actor identity.",
        "Branch protection and signed-commit host policy are not configured or verified by Jurati.",
    )
    return AuditDiagnostics(
        reviewable_git_context=True,
        signed_commits=False,
        append_only_events=False,
        complete_lifecycle_events=False,
        active_refs_audit_safe=False,
        authenticated_identity=False,
        host_protection_verified=False,
        blockers=blockers,
    )


def _print_audit_diagnostics(diagnostics: AuditDiagnostics) -> bool:
    audit_ready = (
        diagnostics.signed_commits
        and diagnostics.append_only_events
        and diagnostics.complete_lifecycle_events
        and diagnostics.active_refs_audit_safe
        and diagnostics.authenticated_identity
        and diagnostics.host_protection_verified
    )

    click.echo("Audit/compliance claim gate:")
    click.echo(f"  reviewable git-backed context: {_yes_no(diagnostics.reviewable_git_context)}")
    click.echo(f"  immutable ledger claim:       {_yes_no(audit_ready)}")
    click.echo(f"  tamper-evident ledger claim:  {_yes_no(audit_ready)}")
    click.echo(f"  SOC2-ready audit evidence:    {_yes_no(audit_ready)}")
    click.echo(f"  signed Jurati commits:        {_yes_no(diagnostics.signed_commits)}")
    click.echo(f"  append-only event evidence:   {_yes_no(diagnostics.append_only_events)}")
    click.echo(f"  complete lifecycle events:    {_yes_no(diagnostics.complete_lifecycle_events)}")
    click.echo(f"  L0 active refs audit-safe:    {_yes_no(diagnostics.active_refs_audit_safe)}")
    click.echo(f"  authenticated actor identity: {_yes_no(diagnostics.authenticated_identity)}")
    click.echo(f"  host protection verified:     {_yes_no(diagnostics.host_protection_verified)}")
    click.echo("  allowed claim:                reviewable project context backed by git")
    click.echo(
        "  blocked claims:               immutable ledger, tamper-evident ledger, "
        "SOC2-ready audit trail, authenticated authorship"
    )
    if diagnostics.blockers:
        click.echo("  blockers:")
        for blocker in diagnostics.blockers:
            click.echo(f"    - {blocker}")
    return audit_ready


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
        cache_hint = _cache_failure_hint(exc)
        if cache_hint:
            click.echo(cache_hint)
        click.echo("  context(): skipped because sync failed")
        return False

    summary = _startup_context_summary(index, datetime.now(UTC))
    click.echo(f"  sync():    ok ({len(index.entries)} entries indexed)")
    click.echo(
        "  context(): ok "
        f"({summary['active']} active, {summary['recent']} recent entries available)"
    )
    return True


def _print_disabled_startup_probe() -> bool:
    click.echo("Startup probe:")
    click.echo("  sync():    skipped (Jurati disabled)")
    click.echo("  startup(): disabled (agents proceed local-only)")
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


def _cache_failure_hint(exc: Exception) -> str | None:
    message = str(exc).lower()
    cache_problem_markers = (
        "read-only file system",
        "permission denied",
        "could not create work tree dir",
        "file exists",
        "not a directory",
    )
    if not any(marker in message for marker in cache_problem_markers):
        return None
    return (
        "  fix: set JURATI_CACHE_DIR to a writable directory, for example "
        "`JURATI_CACHE_DIR=/tmp/jurati-cache jurati doctor --check-startup`."
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


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

    timestamp = _starter_timestamp()
    starter_files = {
        root / "README.md": STARTER_README,
        root / "projects" / "first-shared-context.md": STARTER_PROJECT,
        root / "workflows" / "daily-shared-context-loop.md": STARTER_WORKFLOW,
    }
    starter_files.update(
        {root / relative_path: content for relative_path, content in STARTER_PACKS[pack].items()}
    )
    return {
        path: content.replace(STARTER_TIMESTAMP, timestamp)
        for path, content in starter_files.items()
    }


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
