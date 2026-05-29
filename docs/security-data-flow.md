# Security Data Flow

This page is the short security-review packet for Jurati. It summarizes what
Jurati reads, writes, stores, sends over the network, and how to remove it from
a project.

## Install Footprint

| Path | Trigger | Contents |
|------|---------|----------|
| `CLAUDE.md` | `jurati onboard`, `jurati install-claude-md` | Agent startup instructions that tell the agent to load Jurati context before local exploration. |
| `.claude/settings.json` | `jurati onboard`, `jurati install-claude-md` | Claude Code MCP tool allowlist, including read tools and write tools unless your team edits the file. |
| `.mcp.json` | `jurati onboard`, `jurati mcp-config --write-project` | MCP server config that runs `jurati serve` with the configured remote and client slug. |
| `.jurati/config.yaml` | `jurati onboard`, `jurati doctor --fix-project-config` | Project policy: enabled state, context remote, active handoff policy, TTL, and muted scopes. |
| Context repo | `jurati onboard`, `jurati init`, `jurati quickstart` | Markdown entries with YAML frontmatter, plus normal git history. |
| Local cache | `jurati serve`, `jurati startup`, `jurati doctor --check-startup` | Local checkout and derived indexes for the configured context repo. |
| `.git/jurati-pending/` | Optional capture hook | Pending captured commit-context payloads waiting to flush. |
| `.jurati/read-model.sqlite3*` | Read-model rebuild/query commands | Local SQLite read model derived from context entries. |

## Reads

| Source | Trigger | Notes |
|--------|---------|-------|
| Context repo Markdown | `sync()`, `startup()`, `context()`, `query()`, `search()`, `read()` | Reads happen from a local cache after sync/fetch. Restricted entries are excluded from search, context, and BM25 input. |
| Project config | CLI and MCP startup | Reads `.jurati/config.yaml`, `.mcp.json`, and Claude settings to diagnose setup. |
| Git remotes | Sync/startup/doctor with a configured remote | Fetches the source-of-truth branch and active refs when active handoffs are enabled. |
| GitHub PRs/issues | Only when GitHub signal env vars are configured | Reads configured, labeled sources for project signals. |
| Jira issues | Only when Jira env vars are configured | Reads configured Jira projects using the provided credentials. |
| Local git metadata | Capture, hygiene, import, and diagnostics commands | Used for reviewable writes, lifecycle cleanup, and optional hooks. |

Jurati does not collect query text, read receipts, editor activity, online
presence, or participation telemetry.

## Writes

| Action | Trigger | Destination |
|--------|---------|-------------|
| Active handoff | `record(type="active", ...)` when active handoffs are enabled | Short-lived active git ref in the context repo. |
| Project update | `record(type="project", ...)` | Reviewable branch or pull request, depending on command path and environment. |
| Decision/workflow/principle | `propose(...)` | Reviewable branch or pull request. |
| Expire context | `expire(id=...)` | Active ref deletion for active entries, or reviewable lifecycle update for durable entries. |
| Hygiene cleanup | `hygiene()` or curation commands | Reviewable cleanup PRs for stale or revalidation-due entries. |
| Setup repair | `jurati doctor --fix-project-config` | Project-local config and MCP/agent instruction files. |

All record/propose write content passes content-safety checks before it reaches
the context repo. Credential-shaped secrets are blocked. PII, confidentiality
terms, and personnel content can require review.

## Network Egress

Jurati has no vendor service endpoint.

| Destination | Trigger | Credentials |
|-------------|---------|-------------|
| Python package index or GitHub source URL | Install commands such as `pip install`, `pipx install`, or `uvx --from` | Package manager configuration. |
| Configured context git remote | `sync()`, `startup()`, `serve`, `doctor --check-startup`, write tools | User's git/SSH/HTTPS credentials. |
| GitHub API | GitHub signal provider or PR-creating write paths | `gh` auth or GitHub token from the environment. |
| Jira API | Jira signal provider | Jira URL/project env vars and Jira token. |

If providers are not configured, Jurati does not contact them. The MCP server
runs over stdio; network activity comes from configured git/provider operations.

## Retention And Deletion

| Data | Retention | Removal |
|------|-----------|---------|
| Durable Markdown entries | Normal git history | Use reviewed lifecycle changes; git history remains unless repo admins rewrite history. |
| Active handoffs | Project TTL, default 72 hours when configured | Expire through `expire()` or delete active refs according to team policy. |
| Local cache | Until removed by the user | Remove the configured `JURATI_CACHE_DIR` path. |
| Read-model SQLite files | Until rebuilt or removed | Delete `.jurati/read-model.sqlite3*`. |
| Pending capture payloads | Until flushed or removed | Delete `.git/jurati-pending/` if the capture hook is abandoned. |

The privacy boundary is API-layer, not storage-layer. Anyone with access to the
context repo can read raw Markdown files and git history, including identities
present in commits or entry metadata.

## Enterprise Controls

- Use repo permissions and branch protection on the context repo.
- Use one context repo per legal, customer, or confidentiality boundary.
- Keep `active_refs_enabled` off for projects that forbid short-lived handoffs.
- Review `.claude/settings.json` before committing it; it allowlists read and
  write MCP tools for Claude Code.
- Avoid global onboarding for multi-client work unless cross-client context is
  intentional and approved.
- Configure GitHub/Jira providers only for approved sources.
- Rotate git/provider credentials through your normal credential-management
  process.
- Treat `jurati doctor --check-startup` as the setup smoke test before rollout.
