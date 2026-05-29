# Install And Troubleshooting

This guide covers the public setup path for Jurati. The README explains the
product model; this page is for getting a project connected and diagnosing the
common failure modes.

## Requirements

- Python 3.12 or newer
- Git
- For solo/local use: no git remote required
- For team use: a git remote for the shared context repo
- For in-agent use: an MCP-capable coding agent client, such as Claude Code

Jurati's automated installer is Claude Code-first today. Other MCP clients can
use the same server, but may need manual client-specific MCP configuration.
The CLI fallback is `jurati startup --format markdown`, which prints context any
agent can read.

## Install

```bash
pip install jurati
```

From source:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

For one-off setup without installing into the current environment:

```bash
uvx --from git+https://github.com/ostinato-forge/jurati.git \
  jurati onboard --remote git@github.com:your-org/jurati-knowledge.git
```

## Onboard A Project

### Solo Local Setup

Use this path when you only want continuity for yourself and do not need a
shared remote:

```bash
cd /path/to/your-project
jurati onboard --local --yes
jurati doctor --check-startup
```

This creates a local context repo, installs project agent instructions, writes
MCP config, and enables handoffs for this project.

After `jurati doctor --check-startup`, expect:

```text
Startup probe:
sync():    ok
context(): ok
Ready for `jurati serve`: yes
```

Restart your coding agent. To test the handoff path, say:

```text
Save where I left off.
```

In a later session, ask:

```text
Where was I?
```

### Team Setup

Ask the team lead or platform owner for the shared context repo remote URL,
then run guided onboarding from the project repo:

```bash
cd /path/to/your-project
jurati onboard --remote git@github.com:your-org/jurati-knowledge.git
```

For scripted setup:

```bash
jurati onboard \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --knowledge-repo ./jurati-knowledge \
  --project-repo . \
  --pack engineering \
  --yes
```

If this is a new knowledge repo, initialize and push it:

```bash
cd ./jurati-knowledge
git init -b main
git add .
git commit -m "docs: initialize knowledge repo"
git remote add origin git@github.com:your-org/jurati-knowledge.git
git push -u origin main
```

Team members should use the same remote URL. If local setup was used by
mistake, rerun onboarding with `--remote <team-context-repo>`.

### Many Clients Or Confidential Projects

Use one context repo per legal, customer, or confidentiality boundary. Do not
reuse the same remote across unrelated clients unless they are intentionally
allowed to share context.

For multi-client work:

- Prefer project-local onboarding over `jurati onboard --global`.
- Run `jurati status` in each repo and confirm the discovered remote before
  saving handoffs or decisions.
- Treat `muted_scopes` as relevance filters, not confidentiality controls.
- Keep generated project config out of a client repo unless that client has
  approved it.
- Remove local cache and generated config during client offboarding.

## Files Created Or Modified

| Path | Purpose | Commit? |
|------|---------|---------|
| `CLAUDE.md` | Agent startup instructions for this project. | Commit only when this is team-approved project guidance. Keep personal instructions local. |
| `.mcp.json` | Project MCP server config. | Commit for team-wide setup if your client supports project MCP config. |
| `.jurati/config.yaml` | Project participation marker, remote URL, active handoff policy, and TTL. | Commit for team-wide setup. |
| `.claude/settings.json` | Claude Code tool permission allowlist. | Commit only if your team standardizes Claude Code permissions in-repo. |
| Local context repo path | The Markdown context store created by solo/local onboarding. | Do not commit inside your app repo unless you intentionally placed it there. |

## Verify

```bash
jurati doctor --check-startup
```

For a team rollout, include the team readiness report:

```bash
jurati doctor --team --check-startup
```

Then restart your MCP client and start a normal task. You should not need to
ask the agent to call tool names directly. If you want a human-readable summary
from the CLI, run:

```bash
jurati status
```

If project configuration is incomplete:

```bash
jurati doctor --fix-project-config --team
jurati doctor --team --check-startup
```

## Daily Use

You can use natural language with the coding agent:

```text
"Save this handoff for tomorrow."
"Record this as a project decision: use server-driven token rotation."
"What did we decide about the auth migration?"
```

The agent should translate those requests to `record()`, `propose()`, `query()`,
or `context()` as appropriate. You should not need to manage entry IDs, branch
names, active refs, or knowledge-repo internals during normal work.

## Configuration

| Variable | Purpose |
|----------|---------|
| `JURATI_KNOWLEDGE_REMOTE` | Git remote for the knowledge repo |
| `JURATI_ACTIVE_REFS_ENABLED` | Enable instant active context sharing |
| `JURATI_ACTIVE_REF_TTL_HOURS` | Maximum TTL for active context entries |
| `JURATI_SIGNAL_PROVIDER` | Signal source: `github` or `jira` |
| `JURATI_PR_SIGNAL_REPOS` | Repos for GitHub PR signals |
| `JURATI_JIRA_BASE_URL` | Jira instance URL |
| `JURATI_JIRA_PROJECTS` | Jira project keys |

## Troubleshooting

### The Agent Skips Context

Run:

```bash
jurati doctor --team --check-startup --strict
```

If the startup contract or MCP permissions are missing, repair project config:

```bash
jurati doctor --fix-project-config --team
```

Restart the MCP client after changing project configuration.

### `sync()` Or `context()` Is Unavailable

Check the knowledge remote and local cache:

```bash
jurati doctor --team --check-startup
jurati status
```

If the knowledge repo moved, regenerate project config with the new remote. If
the cache is corrupted, remove the local Jurati cache for that remote and run
`jurati doctor --team --check-startup` again.

### Active Handoffs Do Not Appear

`jurati onboard` enables active handoffs for the onboarded project by writing
`active_refs_enabled: true` in `.jurati/config.yaml`. If you installed pieces
manually, repaired an older project, or your team disabled handoffs, enable
them only when the repo policy allows short-lived handoffs:

```yaml
active_refs_enabled: true
active_ref_ttl_hours: 72
```

Then regenerate MCP config and verify:

```bash
jurati mcp-config --remote <knowledge-remote> --write-project
jurati doctor --team --check-startup
```

If you only set `JURATI_ACTIVE_REFS_ENABLED=true` in your shell, the behavior is
local to that process. Project config is the preferred team-visible policy.

### Client Support

| Client | Setup status | Verification |
|--------|--------------|--------------|
| Claude Code | First-class automated path. `jurati onboard` writes `CLAUDE.md`, `.claude/settings.json`, and `.mcp.json`. | `jurati doctor --check-startup`, then restart Claude Code. |
| Cursor | Generic MCP path. Use `.mcp.json` if your Cursor setup reads project MCP config; otherwise copy `jurati mcp-config --remote <url>` output into Cursor's MCP settings. | Run `jurati doctor --check-startup`, then confirm Cursor can see the Jurati MCP tools. |
| Gemini CLI | Generic MCP path. Run `jurati mcp-config --remote <url> --client-slug gemini-cli` and install the JSON where Gemini CLI expects MCP servers. | Run `jurati doctor --check-startup`, then verify Gemini CLI can call the Jurati MCP server. |
| No MCP client | CLI fallback. | Run `jurati startup --format markdown` and give the output to the agent. |

Dedicated Cursor and Gemini installers are not implemented yet. The underlying
server is generic MCP; the one-command onboarding experience is currently best
for Claude Code.

## Glossary

| Term | Meaning |
|------|---------|
| Context repo | The git repo that stores Jurati Markdown entries. Some config variables still call this the knowledge repo. |
| MCP | The protocol AI coding tools use to connect to external tools like Jurati. |
| Startup contract | Agent instructions that tell the agent to load Jurati context before local exploration. |
| Active handoff | Short-lived current-work context saved for the next session. |
| Reviewed path | Durable decisions and workflows saved through pull requests. |
| Local cache | A local checkout/index of the context repo used for reads after sync. |

## Remove From A Project

To stop using Jurati in one project:

```bash
jurati disable
```

Then remove project wiring if you no longer want the files:

```bash
rm .mcp.json
rm -rf .jurati .claude
```

If `CLAUDE.md` contains other project guidance, remove only the Jurati section.

### Writes Are Blocked

Jurati evaluates writes before publishing. Credentials and secrets are blocked.
PII, confidentiality terms, and personnel content can require review. Remove the
sensitive content or route the entry through the reviewed path.

### PR Or Jira Signals Do Not Appear

Only configured, labeled sources enter the signal path.

For GitHub:

```bash
JURATI_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2
```

For Jira:

```bash
JURATI_SIGNAL_PROVIDER=jira
JURATI_JIRA_BASE_URL=https://jira.example.com
JURATI_JIRA_PROJECTS=PROJ1,PROJ2
JIRA_API_TOKEN=your-token
```

Unlabeled PRs and issues are ignored by design.
