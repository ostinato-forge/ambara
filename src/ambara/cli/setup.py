# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Knowledge repo setup, onboarding, and demo commands for the CLI."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import frontmatter

from ambara.cli.install import (
    CLIENT_CONFIGS,
    _install_claude_md,
    _install_instructions,
    _mcp_config_json,
    _mcp_config_payload,
    _write_project_mcp_config,
    _write_settings_json,
)
from ambara.cli.project_config import (
    _project_active_ref_env,
    _read_project_team_config,
    _write_project_team_config,
)
from ambara.core.graph import validate_entry_links
from ambara.core.index import Index, parse_entry
from ambara.core.paths import TYPE_DIRS
from ambara.core.validate import validate_entry

SCAFFOLD_DIRS = [
    "principles",
    "decisions",
    "workflows",
    "projects",
    "active",
    "archive",
    ".ambara",
]


DEFAULT_CONFIG = """\
# Config schema version. Entry frontmatter has its own schema_version.
schema_version: 1
main_branch: main
active_ref_prefix: ambara/active
levels:
  active: [L0]
  project: [L1]
  workflow: [L2]
  decision: [L2, L3]
  principle: [L3]
review:
  low_ceremony_labels: [ambara-record]
  required_review_levels: [L2, L3]
expiry:
  active_ttl_hours: 72
active_refs_enabled: true
"""

STARTER_TIMESTAMP = "__AMBARA_STARTER_TIMESTAMP__"


def _starter_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


STARTER_README = """\
# Ambara Knowledge Repo

This repository is shared context for people and AI coding agents.

Ambara stores durable knowledge as markdown files with YAML frontmatter. Agents
query this repo before they start work, record short-lived active context while
they work, and propose lasting decisions or workflows through review branches
and requests.

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
ambara validate .
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
projects: [ambara]
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

Before work starts, query Ambara for prior decisions, project state, and known
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

Before writing, query Ambara for prior course decisions, lab constraints,
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

Before implementation, query Ambara for architecture decisions, release rules,
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
expectations should be proposed as Ambara decisions instead of being left only
in chat, tickets, or transient review comments.
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

DEMO_SIGNAL_FIXTURE = {
    "signals": [
        {
            "repo": "org/api",
            "number": 42,
            "url": "https://github.com/org/api/pull/42",
            "title": "Demo handoff needs review",
            "body_excerpt": "Review the API handoff before continuing implementation.",
            "author": "demo-user",
            "state": "open",
            "labels": ["ambara", "handoff"],
            "created_at": "2026-06-03T10:00:00Z",
            "updated_at": "2026-06-03T10:30:00Z",
            "changed_paths": ["active/demo-api-handoff.md"],
        },
        {
            "provider": "gitlab",
            "signal_id": "gitlab:org/api:merge_request:77",
            "repo": "org/api",
            "number": 77,
            "url": "https://gitlab.com/org/api/-/merge_requests/77",
            "title": "Demo GitLab handoff follow-up",
            "body_excerpt": "A GitLab merge request is carrying the same handoff path.",
            "author": "demo-user",
            "state": "open",
            "labels": ["ambara", "handoff"],
            "created_at": "2026-06-03T10:05:00Z",
            "updated_at": "2026-06-03T10:35:00Z",
            "changed_paths": ["active/demo-api-handoff.md"],
        },
    ]
}


def register_setup_commands(main: click.Group) -> None:
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
        click.echo("Next: run `ambara validate <path>` and push this directory to a git remote.")

    @main.command()
    @click.option(
        "--remote",
        envvar="AMBARA_KNOWLEDGE_REMOTE",
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
        default="ambara",
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
    @click.argument("path", default="./ambara-knowledge", type=click.Path())
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

        click.echo("Ambara quickstart")
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
        click.echo("What Ambara will do:")
        click.echo("  - read shared markdown knowledge from this git repo")
        click.echo("  - answer agent queries from a local cache after sync")
        click.echo("  - write only when record/propose/expire is explicitly called")
        click.echo(
            "  - use active refs for short-lived context and review branches for durable knowledge"
        )
        click.echo("  - avoid query logging, read receipts, participation tracking, and telemetry")
        click.echo("")

        if remote:
            click.echo("MCP config:")
            click.echo(_mcp_config_json(remote, client_slug, command_name))
            click.echo("")
            click.echo("Next steps:")
            click.echo(f"  1. cd {root}")
            click.echo("  2. git init")
            click.echo('  3. git add . && git commit -m "docs: initialize ambara knowledge repo"')
            click.echo(f"  4. git remote add origin {remote}")
            click.echo("  5. git push -u origin main")
            click.echo("  6. Paste the MCP config above into your client.")
            click.echo("  7. Run: ambara doctor --check-startup")
            click.echo("  8. Run: ambara serve --check")
            click.echo("")
            click.echo(
                "GitHub and GitLab are first-class review backends. Other git remotes can "
                "still start with branch-only fallback."
            )
        else:
            click.echo("Next steps:")
            click.echo(f"  1. cd {root}")
            click.echo("  2. git init")
            click.echo('  3. git add . && git commit -m "docs: initialize ambara knowledge repo"')
            click.echo("  4. Create a git remote and push this repo.")
            click.echo("  5. Run: ambara mcp-config --remote <git-url>")
            click.echo("  6. Run: ambara doctor --check-startup")
            click.echo("  7. Run: ambara serve --check")
            click.echo("")
            click.echo(
                "GitHub and GitLab are first-class review backends. Other git remotes can "
                "still start with branch-only fallback."
            )

    @main.command("demo")
    @click.option(
        "--path",
        "demo_path",
        default="./ambara-demo",
        show_default=True,
        type=click.Path(file_okay=False),
        help="Directory where the local demo project will be created.",
    )
    @click.option(
        "--force",
        is_flag=True,
        help="Overwrite Ambara-created demo files if the demo directory already exists.",
    )
    def demo_cmd(demo_path: str, force: bool) -> None:
        """Create a local, no-network demo that proves the core Ambara loop."""
        root = Path(demo_path)
        if root.exists() and any(root.iterdir()) and not force:
            raise click.ClickException(
                f"{root} already exists and is not empty. Pass --force to refresh demo files."
            )

        knowledge = root / "knowledge"
        project = root / "project"
        cache = root / "cache"
        value_ledger = root / "value-ledger.jsonl"
        source_fixture = root / "signals.json"
        site = root / "site"
        proof_script = root / "run-proof.sh"

        root.mkdir(parents=True, exist_ok=True)
        cache.mkdir(parents=True, exist_ok=True)
        project.mkdir(parents=True, exist_ok=True)
        knowledge.mkdir(parents=True, exist_ok=True)

        written = 0
        for relative_path, content in _demo_knowledge_files(datetime.now(UTC)).items():
            if _write_demo_file(knowledge / relative_path, content, force=force):
                written += 1

        source_fixture_content = json.dumps(DEMO_SIGNAL_FIXTURE, indent=2) + "\n"
        if _write_demo_file(source_fixture, source_fixture_content, force=force):
            written += 1

        if _write_demo_file(project / "README.md", _demo_project_readme(), force=force):
            written += 1
        if _write_demo_file(project / ".gitignore", _demo_project_gitignore(), force=force):
            written += 1
        if _write_demo_file(proof_script, _demo_proof_script(), force=force):
            written += 1
        proof_script.chmod(0o755)

        _init_or_update_demo_git_repo(knowledge, message="Initialize Ambara demo knowledge")

        remote = str(knowledge.resolve())
        _install_claude_md(project, remote)
        _write_project_team_config(project, remote=remote, active_refs_enabled=True)
        project_config = _read_project_team_config(project)
        if project_config.read_error:
            raise click.ClickException(
                f"Cannot read demo project config: {project_config.read_error}"
            )
        payload = _mcp_config_payload(
            remote,
            "ambara-demo",
            "ambara",
            policy_env=_project_active_ref_env(project_config),
        )
        raw_servers = payload.get("mcpServers")
        if isinstance(raw_servers, dict):
            server = next(iter(raw_servers.values()))
            if isinstance(server, dict):
                env = server.setdefault("env", {})
                if isinstance(env, dict):
                    env["AMBARA_SOURCE_REPOS"] = "org/api"
                    env["AMBARA_SOURCE_FIXTURE"] = str(source_fixture.resolve())
        _write_project_mcp_config(project / ".mcp.json", payload)
        _init_or_update_demo_git_repo(project, message="Initialize Ambara demo project")

        click.echo("Ambara demo created")
        click.echo("")
        click.echo(f"  demo root:       {root.resolve()}")
        click.echo(f"  project repo:    {project.resolve()}")
        click.echo(f"  knowledge repo:  {knowledge.resolve()}")
        click.echo(f"  source fixture:  {source_fixture.resolve()}")
        click.echo(f"  proof script:    {proof_script.resolve()}")
        click.echo(f"  files refreshed: {written}")
        click.echo("")
        click.echo("Proof commands:")
        click.echo(f"  cd {root.resolve()}")
        click.echo("  ./run-proof.sh")
        click.echo("")
        click.echo("Expanded proof commands:")
        click.echo(f"  cd {project.resolve()}")
        click.echo(f"  AMBARA_CACHE_DIR={cache.resolve()} ambara doctor --check-startup")
        click.echo(
            "  "
            f"AMBARA_CACHE_DIR={cache.resolve()} "
            f"AMBARA_VALUE_LEDGER_PATH={value_ledger.resolve()} "
            f"AMBARA_SOURCE_REPOS=org/api "
            f"AMBARA_SOURCE_FIXTURE={source_fixture.resolve()} "
            'ambara startup --goal "continue the API handoff" --format md '
            "--output .ambara/context.md"
        )
        click.echo(f"  AMBARA_CACHE_DIR={cache.resolve()} ambara read demo-api-handoff")
        click.echo(f"  ambara value --ledger {value_ledger.resolve()}")
        click.echo(
            f"  AMBARA_CACHE_DIR={cache.resolve()} ambara html {knowledge.resolve()} "
            f"--output {site.resolve()}"
        )
        click.echo("")
        click.echo("Expected proof:")
        click.echo("  - startup returns compact context before local exploration")
        click.echo("  - full bodies stay deferred until read")
        click.echo("  - restricted entries are hidden from broad context and static HTML")
        click.echo("  - active record, proposal, import, and capture write paths are explicit")
        click.echo("  - value receipts are app-payload estimates only")

    @main.command()
    @click.option(
        "--remote",
        envvar="AMBARA_KNOWLEDGE_REMOTE",
        help="Git remote URL for the team knowledge repo. Prompted when omitted.",
    )
    @click.option(
        "--knowledge-repo",
        default="./ambara-knowledge",
        show_default=True,
        help="Local path for the knowledge repo scaffold.",
    )
    @click.option(
        "--project-repo",
        default=".",
        show_default=True,
        help="Project repo to connect to Ambara.",
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
        default="ambara",
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
        "--client",
        "client_name",
        type=click.Choice(sorted(CLIENT_CONFIGS)),
        default="claude",
        show_default=True,
        help="AI coding agent to configure.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        help="Preview files and config without writing.",
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
        client_name: str,
        dry_run: bool,
        is_global: bool,
    ) -> None:
        """Create local knowledge and project wiring in one guided run."""
        click.echo("Ambara onboarding (dry run)" if dry_run else "Ambara onboarding")
        click.echo("")

        if is_global and client_name != "claude":
            raise click.ClickException("--global currently supports --client claude only.")

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

        if dry_run:
            effective_remote = remote or str(root.resolve())
            click.echo("Would create:")
            for dirname in SCAFFOLD_DIRS:
                click.echo(f"  {root / dirname}/")
            click.echo(f"  {root / '.ambara' / 'config.yaml'}")
            if examples:
                click.echo(f"  starter entries from pack: {pack}")
            click.echo("")

            payload = _mcp_config_payload(effective_remote, client_slug, command_name)
            if is_global:
                home = Path.home()
                click.echo("Would configure:")
                click.echo(f"  {home / '.claude' / 'CLAUDE.md'}")
                click.echo(f"  {home / '.claude' / 'settings.json'}")
                click.echo(f"  {home / '.claude.json'}")
            else:
                client_config = CLIENT_CONFIGS[client_name]
                project = Path(project_repo)
                click.echo("Would configure:")
                click.echo(f"  {project / client_config.instructions_path}")
                click.echo(f"  {project / '.ambara' / 'config.yaml'}")
                if client_config.settings_path:
                    click.echo(f"  {project / client_config.settings_path}")
                click.echo(f"  {project / client_config.mcp_config_path}")
            click.echo("")
            click.echo("MCP config:")
            click.echo(json.dumps(payload, indent=2))
            click.echo("")
            click.echo("No files were written.")
            return

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
            click.echo("Ambara is now available in every Claude Code session.")
            click.echo("Restart any running sessions for the changes to take effect.")
        else:
            project = Path(project_repo)
            client_config = CLIENT_CONFIGS[client_name]
            _install_instructions(project, remote, client_config=client_config, solo=local_mode)
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
            mcp_path = project / client_config.mcp_config_path
            server_name = _write_project_mcp_config(mcp_path, payload)
            click.echo(f"Updated {mcp_path} with MCP server {server_name!r}.")

            click.echo("")
            if local_mode:
                click.echo("Local onboarding complete. Handoffs are enabled.")
            else:
                click.echo("Onboarding complete. Handoffs are enabled.")
            click.echo("")
            click.echo("What changed:")
            click.echo(f"  - knowledge repo:       {root}")
            click.echo(f"  - agent instructions:   {project / client_config.instructions_path}")
            click.echo(f"  - project config:       {project / '.ambara' / 'config.yaml'}")
            if client_config.settings_path:
                click.echo(f"  - tool permissions:     {project / client_config.settings_path}")
            click.echo(f"  - MCP server config:    {mcp_path}")
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
                click.echo(
                    '     git add . && git commit -m "docs: initialize ambara knowledge repo"'
                )
                click.echo(f"     git remote add origin {remote}")
                click.echo("     git push -u origin main")
                click.echo("  2. Restart your coding agent in the project repo.")
                click.echo("  3. Verify the setup:")
                click.echo("     ambara doctor --check-startup")
                click.echo("")
                click.echo(
                    "GitHub and GitLab are first-class review backends. Other git remotes "
                    "can still start with branch-only fallback."
                )


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

    if _write_if_missing(root / ".ambara" / "config.yaml", DEFAULT_CONFIG):
        created.append(root / ".ambara" / "config.yaml")

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


def _demo_knowledge_files(now: datetime) -> dict[str, str]:
    created = now.astimezone(UTC).replace(microsecond=0)
    updated = created.isoformat().replace("+00:00", "Z")
    expires = (created + timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    stale_created = "2025-01-15T09:00:00Z"
    stale_review = "2025-02-15T09:00:00Z"
    return {
        "decisions/demo-use-reviewed-context.md": f"""\
---
schema_version: 2
id: demo-use-reviewed-context
title: Use reviewed context before local exploration
type: decision
level: L2
status: active
created_at: {updated}
updated_at: {updated}
expires_at: null
review_after: null
projects: [ambara-demo]
tags: [startup, governance]
supersedes: []
superseded_by: null
sensitivity: normal
visibility: internal
review:
  required: true
  pr: "https://github.com/example/ambara-knowledge/pull/1"
---

Agents must use Ambara startup context before reading project files or changing
code. Startup context is compact by default; agents should use read or read_many
only for entries whose source text they directly rely on.
""",
        "workflows/demo-startup-loop.md": f"""\
---
schema_version: 2
id: demo-startup-loop
title: Demo startup and selective-read loop
type: workflow
level: L2
status: active
created_at: {updated}
updated_at: {updated}
expires_at: null
review_after: null
projects: [ambara-demo]
tags: [workflow, demo]
supersedes: []
superseded_by: null
sensitivity: normal
visibility: internal
review:
  required: true
  pr: "https://github.com/example/ambara-knowledge/pull/2"
---

Run startup for the current goal, inspect the compact packet, then read only
the entries that the work depends on. Record short-lived handoffs with active
context and propose durable decisions for review.
""",
        "projects/demo-launch-status.md": f"""\
---
schema_version: 2
id: demo-launch-status
title: Ambara demo launch status
type: project
level: L1
status: active
created_at: {updated}
updated_at: {updated}
expires_at: null
review_after: null
projects: [ambara-demo]
tags: [launch, proof]
supersedes: []
superseded_by: null
sensitivity: normal
visibility: internal
review:
  required: true
  pr: "https://github.com/example/ambara-knowledge/pull/3"
---

The release proof should show a fresh agent starting from reviewed context,
following read hints, recording an active handoff only when asked, and leaving
durable decisions to review.
""",
        "active/demo-api-handoff.md": f"""\
---
schema_version: 2
id: demo-api-handoff
title: Continue the API handoff
type: active
level: L0
status: active
created_at: {updated}
updated_at: {updated}
expires_at: {expires}
review_after: null
projects: [ambara-demo, api]
tags: [handoff, demo]
supersedes: []
superseded_by: null
sensitivity: normal
visibility: internal
review:
  required: false
  pr: null
---

Continue the API handoff by checking the startup packet first, then reading
this source entry before changing any API files. The next step is to verify
the demo proof commands still show deferred bodies and app-payload value
receipts.
""",
        "projects/demo-stale-status.md": f"""\
---
schema_version: 2
id: demo-stale-status
title: Retired demo migration status
type: project
level: L1
status: active
created_at: {stale_created}
updated_at: {stale_created}
expires_at: null
review_after: {stale_review}
projects: [ambara-demo]
tags: [stale-demo]
supersedes: []
superseded_by: null
sensitivity: normal
visibility: internal
review:
  required: true
  pr: "https://github.com/example/ambara-knowledge/pull/4"
---

This intentionally stale entry exists so Ambara can show lifecycle and curation
signals without silently deleting historical context.
""",
        "decisions/demo-restricted-token-policy.md": f"""\
---
schema_version: 2
id: demo-restricted-token-policy
title: Restricted token handling note
type: decision
level: L2
status: active
created_at: {updated}
updated_at: {updated}
expires_at: null
review_after: null
projects: [ambara-demo]
tags: [security, restricted]
supersedes: []
superseded_by: null
sensitivity: restricted
visibility: internal
review:
  required: true
  pr: "https://github.com/example/ambara-knowledge/pull/5"
---

This restricted entry is intentionally hidden from broad context, search,
static HTML, and read-model indexes. It should not appear in demo startup
packets.
""",
    }


def _demo_project_readme() -> str:
    return """\
# Ambara Demo Project

This local project is wired to the sibling `knowledge/` repo by `ambara demo`.

Run `../run-proof.sh` to see startup context, selective reads, value receipts,
restricted-entry filtering, explicit write paths, import review branches, and
static HTML inspection.
"""


def _demo_proof_script() -> str:
    return """\
#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT="$ROOT/project"
KNOWLEDGE="$ROOT/knowledge"
CACHE="$ROOT/cache"
LEDGER="$ROOT/value-ledger.jsonl"
SIGNALS="$ROOT/signals.json"
SITE="$ROOT/site"
RUN_STAMP=$(date -u +%Y%m%d%H%M%S)
RUN_ID="$RUN_STAMP-$$"
CAPTURE_SHA=$(printf "%040d" "$RUN_STAMP")

if ! command -v ambara >/dev/null 2>&1; then
  echo "ambara is not on PATH; install Ambara first." >&2
  exit 127
fi

export AMBARA_KNOWLEDGE_REMOTE="$KNOWLEDGE"
export AMBARA_CACHE_DIR="$CACHE"
export AMBARA_VALUE_LEDGER_PATH="$LEDGER"
export AMBARA_SOURCE_REPOS="org/api"
export AMBARA_SOURCE_FIXTURE="$SIGNALS"
export AMBARA_ACTIVE_REFS_ENABLED=true
export AMBARA_CLIENT_SLUG=ambara-demo

mkdir -p "$CACHE" "$PROJECT/.ambara" "$SITE"
cd "$PROJECT"

echo "[1/14] validate knowledge repo"
ambara validate "$KNOWLEDGE" > "$ROOT/validate.txt"

echo "[2/14] doctor startup contract"
ambara doctor --check-startup > "$ROOT/doctor.txt"

echo "[3/14] source doctor and fixture smoke"
ambara sources doctor \\
  --provider fixture \\
  --fixture "$SIGNALS" \\
  --repo org/api \\
  --json > "$ROOT/sources-doctor.json"
grep -q '"status": "ok"' "$ROOT/sources-doctor.json"
ambara source-smoke \\
  --provider fixture \\
  --fixture "$SIGNALS" \\
  --repo org/api \\
  --json > "$ROOT/source-smoke.json"
grep -q '"provider": "fixture"' "$ROOT/source-smoke.json"

echo "[4/14] compile startup context"
ambara startup --goal "continue the API handoff" --format json --output "$ROOT/startup.json"
ambara startup --goal "continue the API handoff" --format md --output .ambara/context.md

echo "[5/14] verify restricted context is absent from startup"
if grep -q "demo-restricted-token-policy\\|This restricted entry" .ambara/context.md; then
  echo "restricted content leaked into startup context" >&2
  exit 1
fi
grep -q "https://gitlab.com/org/api/-/merge_requests/77" "$SIGNALS"

echo "[6/14] read explicitly selected source body"
ambara read demo-api-handoff > "$ROOT/read-demo-api-handoff.md"
grep -q "Continue the API handoff" "$ROOT/read-demo-api-handoff.md"

echo "[7/14] record short-lived active context"
ambara record \\
  --type active \\
  --title "Demo proof follow-up $RUN_ID" \\
  --content "The release proof recorded this short-lived handoff from the local demo." \\
  --projects ambara-demo \\
  --tags proof > "$ROOT/record-active.txt"
grep -q "Recorded active context" "$ROOT/record-active.txt"

echo "[8/14] propose durable context on a review branch"
ambara propose \\
  --type decision \\
  --title "Demo proof keeps durable knowledge reviewed $RUN_ID" \\
  --content "Durable demo updates should land through a reviewed branch." \\
  --projects ambara-demo \\
  --tags proof > "$ROOT/propose-decision.txt"
grep -q "Proposed on branch" "$ROOT/propose-decision.txt"

echo "[9/14] plan and materialize a docs import review branch"
mkdir -p docs
cat > docs/demo-adr.md <<'MARKDOWN'
# Demo Imported ADR

Use Ambara release proof fixtures for onboarding and smoke tests.
MARKDOWN
ambara import-docs \\
  --dry-run \\
  --repo "$KNOWLEDGE" \\
  --mode adr \\
  --project ambara-demo \\
  --tag proof \\
  docs/demo-adr.md > "$ROOT/import-docs-dry-run.txt"
grep -q "Summary: 1 create, 0 skip, 0 reject" "$ROOT/import-docs-dry-run.txt"
ambara import-docs \\
  --repo "$KNOWLEDGE" \\
  --branch "ambara/import-demo-proof-$RUN_ID" \\
  --base main \\
  --mode adr \\
  --project ambara-demo \\
  --tag proof \\
  docs/demo-adr.md > "$ROOT/import-docs.txt"
grep -q "Wrote import review branch" "$ROOT/import-docs.txt"
git -C "$KNOWLEDGE" checkout main >/dev/null 2>&1 || true

echo "[10/14] queue and flush ambient capture"
ambara capture \\
  --message "ambara: demo capture queue proof $RUN_ID" \\
  --commit "$CAPTURE_SHA" \\
  --author demo@example.com \\
  --repo-slug ambara-demo > "$ROOT/capture.txt"
grep -q "queued" "$ROOT/capture.txt"
ambara flush --dry-run > "$ROOT/flush-dry-run.txt"
grep -q "Found 1 pending capture" "$ROOT/flush-dry-run.txt"
ambara flush > "$ROOT/flush.txt"
grep -q "Processed 1, skipped 0, failed 0" "$ROOT/flush.txt"

echo "[11/14] generate static HTML and verify restricted filtering"
ambara html "$KNOWLEDGE" --output "$SITE" > "$ROOT/html.txt"
grep -q "Skipped 1 restricted entries" "$ROOT/html.txt"
if grep -R "demo-restricted-token-policy\\|This restricted entry" "$SITE" >/dev/null 2>&1; then
  echo "restricted content leaked into static HTML" >&2
  exit 1
fi

echo "[12/14] check local agent posture"
ambara posture-check --repo-path "$PROJECT" --json > "$ROOT/posture.json"
grep -q '"agent_start_guardrails_ready": true' "$ROOT/posture.json"

echo "[13/14] show app-payload value receipt"
ambara value --ledger "$LEDGER" > "$ROOT/value.txt"
grep -q "Ambara value" "$ROOT/value.txt"

echo "[14/14] cross-agent file-adapter smoke"
ambara client-smoke \\
  --client codex \\
  --remote "$KNOWLEDGE" \\
  --project-path "$ROOT/codex-agent" \\
  --json > "$ROOT/client-smoke-codex.json"
grep -q '"ok": true' "$ROOT/client-smoke-codex.json"

echo "Ambara release proof passed."
echo "Proof outputs are in $ROOT"
"""


def _demo_project_gitignore() -> str:
    return """\
*.key
*.pem
.env
.env.*
!.env.example
.ambara/context.md
"""


def _write_demo_file(path: Path, content: str, *, force: bool) -> bool:
    if path.exists():
        try:
            current = path.read_text()
        except OSError as exc:
            raise click.ClickException(f"Cannot read {path}: {exc}") from exc
        if current == content:
            return False
        if not force:
            raise click.ClickException(f"{path} already exists. Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _init_or_update_demo_git_repo(path: Path, *, message: str) -> None:
    import subprocess

    if not (path / ".git").exists():
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        ["git", "config", "user.name", "Ambara Demo"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ambara-demo@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if staged.returncode == 1:
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )
    elif staged.returncode != 0:
        message = staged.stderr.strip() or f"Could not inspect git state in {path}"
        raise click.ClickException(message)


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
