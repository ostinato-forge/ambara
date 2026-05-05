"""CLI entry point: jurati serve, jurati init, jurati validate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import click
import frontmatter

from jurati.core.index import parse_entry
from jurati.core.paths import TYPE_DIRS
from jurati.core.validate import validate_entry
from jurati.git.repo import repo_cache_path

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
    """Jurati: shared team memory for people and AI coding agents."""


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

    from jurati.server import mcp

    mcp.run(transport="stdio")


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
    _write_settings_json(root)
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
        click.echo("  7. Run: jurati doctor")
        click.echo("  8. Run: jurati serve --check")
    else:
        click.echo("Next steps:")
        click.echo(f"  1. cd {root}")
        click.echo("  2. git init")
        click.echo('  3. git add . && git commit -m "docs: initialize jurati knowledge repo"')
        click.echo("  4. Create a git remote and push this repo.")
        click.echo("  5. Run: jurati mcp-config --remote <git-url>")
        click.echo("  6. Run: jurati doctor")
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
def mcp_config(remote: str, client_slug: str, command_name: str) -> None:
    """Print a copy-paste MCP config block."""
    click.echo(_mcp_config_json(remote, client_slug, command_name))


@main.command()
@click.option(
    "--strict",
    is_flag=True,
    help="Exit with an error when required setup is missing.",
)
def doctor(strict: bool) -> None:
    """Explain Jurati setup and check whether this machine is ready."""
    ready = _print_doctor()
    if strict and not ready:
        raise click.ClickException("Jurati is not ready; fix the missing items above.")


@main.command()
def explain() -> None:
    """Explain what Jurati does in plain language."""
    click.echo(
        "\n".join(
            [
                "Jurati gives people and AI agents a shared memory backed by git.",
                "",
                "It reads:",
                "  - project status, decisions, workflows, and principles from a knowledge repo",
                "  - local cached content when answering query/read/list requests",
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
        if "Jurati" not in existing:
            claude_md.write_text(existing.rstrip() + "\n\n" + section + "\n")
            click.echo(f"Appended Jurati section to {claude_md}")
        else:
            click.echo(f"Jurati section already present in {claude_md}")
    else:
        claude_md.write_text(section + "\n")
        click.echo(f"Created {claude_md}")

    _write_settings_json(repo)


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

    return None


def _print_doctor() -> bool:
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati"))
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")
    git_path = shutil.which("git")
    gh_path = shutil.which("gh")

    ready = bool(remote and git_path)

    click.echo("Jurati doctor")
    click.echo("")
    click.echo("What Jurati does:")
    click.echo("  - gives humans and AI agents a shared, reviewable memory")
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
    click.echo(f"Ready for `jurati serve`: {'yes' if ready else 'no'}")

    if not ready:
        click.echo("")
        click.echo("Fast path:")
        click.echo("  1. Run: jurati quickstart ./jurati-knowledge")
        click.echo("  2. Push that repo, then set JURATI_KNOWLEDGE_REMOTE to its URL.")
        click.echo("  3. Run: jurati mcp-config --remote <url>")
        click.echo("  4. Run: jurati serve --check")

    return ready


def _status_value(value: str | None) -> str:
    return value if value else "missing"


def _found_value(path: str | None) -> str:
    return path if path else "missing"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _mcp_server_name(remote_url: str) -> str:
    url_hash = hashlib.sha256(remote_url.encode()).hexdigest()[:8]
    return f"jurati-{url_hash}"


def _mcp_config_json(remote: str, client_slug: str, command_name: str) -> str:
    config = {
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
    return json.dumps(config, indent=2)


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

            for error in validate_entry(entry):
                errors.append(f"{relative_path}: {error}")

    return entry_count, errors


def _jurati_settings_allowlist() -> list[str]:
    return [
        "mcp__jurati__context",
        "mcp__jurati__query",
        "mcp__jurati__search",
        "mcp__jurati__sync",
        "mcp__jurati__status",
        "mcp__jurati__read",
        "mcp__jurati__list_entries",
        "mcp__jurati__explain",
        "mcp__jurati__validate",
        "mcp__jurati__hygiene",
        "mcp__jurati__record",
        "mcp__jurati__propose",
        "mcp__jurati__expire",
    ]


def _write_settings_json(repo: Path) -> None:
    settings_dir = repo / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_file = settings_dir / "settings.json"

    data = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    for tool in _jurati_settings_allowlist():
        if tool not in allow:
            allow.append(tool)

    settings_file.write_text(json.dumps(data, indent=2) + "\n")
    click.echo(f"Updated {settings_file}")


def _jurati_claude_md_section(remote: str | None = None) -> str:
    lines = [
        "## Jurati — Team Knowledge",
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
            "**You MUST call `context()` before starting any task.** This surfaces"
            " active work, team decisions, and cross-repo dependencies that affect"
            " your work. Summarize what you learn in 2-3 sentences for the developer.",
            "",
            "### Tool quick-reference",
            "",
            "| Tool | When to use |",
            "|------|-------------|",
            "| `context()` | First thing, every task. Pass `repo` and `goal` for better results. |",
            "| `query(topic=...)` | Deep-dive on a specific topic after context(). |",
            "| `record(type, title, content)` | Capture active context others should know about. |",
            "| `propose(type, title, content)` |"
            " Record a team decision or workflow that needs review. |",
            "| `sync()` | Call silently before context() to get fresh data. |",
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
            ' "recording to Jurati" or "saving to the knowledge repo."',
            "- **State coordination plainly.** If someone's PR blocks this work, say so directly.",
        ]
    )
    return "\n".join(lines)
