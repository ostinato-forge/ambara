# Install And Troubleshooting

This guide covers the public setup path for Ambara. The README explains the
product model; this page is for getting a project connected and diagnosing the
common failure modes.

## Requirements

- Python 3.12 or newer
- Git
- A git remote for the knowledge repo
- An MCP-capable coding agent client, such as Claude Code

## Install

```bash
pip install ambara
```

Fastest proof path before connecting a real project:

```bash
ambara demo
cd ambara-demo
./run-proof.sh
```

That path is local and no-network. It is the fastest way to verify what Ambara
actually does before you depend on agent steering in a live repo.

From source:

```bash
pipx install git+https://github.com/ostinato-forge/ambara.git
```

For one-off setup without installing into the current environment:

```bash
uvx --from git+https://github.com/ostinato-forge/ambara.git \
  ambara onboard --remote <git-remote-url>
```

## Onboard A Project

Run guided onboarding from the project repo:

```bash
cd /path/to/your-project
ambara onboard
```

For scripted setup:

```bash
ambara onboard \
  --remote <git-remote-url> \
  --knowledge-repo ./ambara-knowledge \
  --project-repo . \
  --pack engineering \
  --yes
```

Example remotes:

- GitHub: `git@github.com:your-org/ambara-knowledge.git`
- GitLab: `git@gitlab.com:your-group/ambara-knowledge.git`

If this is a new knowledge repo, initialize and push it:

```bash
cd ./ambara-knowledge
git init -b main
git add .
git commit -m "docs: initialize knowledge repo"
git remote add origin <git-remote-url>
git push -u origin main
```

## Verify

```bash
ambara doctor --team --check-startup
```

Then restart your MCP client and ask the agent to call `explain()` and
`status()`. You should see the configured knowledge remote, local cache, entry
counts, and sync health.

If project configuration is incomplete:

```bash
ambara doctor --fix-project-config --team
ambara doctor --team --check-startup
```

## Human Verification Surfaces

Ambara does not need to stay invisible behind MCP to be useful. The human can
inspect the system directly through:

- `ambara demo` for a local end-to-end proof
- `ambara startup` for a plain context file any agent can read
- `ambara html` for a static browser view of the knowledge repo
- the git-backed knowledge repo itself for review history and provenance

Those surfaces are useful when validating setup, checking what an agent saved,
or proving behavior during rollout.

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

If Ambara only creates a review branch and does not open a review request, the
receipt now says that explicitly. Treat branch-only fallback as a usable review
artifact, but not as an opened review request.

## CI Capture

Ambara includes a shared CI capture entrypoint for explicit commit-driven
capture.

GitHub can use the bundled composite action. GitLab CI or another runner can
call the same entrypoint directly:

```yaml
ambara_capture:
  image: python:3.12
  variables:
    AMBARA_KNOWLEDGE_REMOTE: https://gitlab.com/your-org/team-context.git
    AMBARA_KNOWLEDGE_TOKEN: $AMBARA_KNOWLEDGE_TOKEN
    AMBARA_MAIN_BRANCH: main
  script:
    - pip install ambara
    - python -m ambara.action.capture
```

The capture path expects:

- `knowledge_remote`
- `knowledge_token`
- `main_branch`

It bootstraps the local knowledge repo from the declared remote, applies the
authenticated remote for the detected forge when a token is present, fetches the configured main
branch, and then processes `ambara:` commit messages.

Capture through the action uses the content-policy gate in addition to secret
scanning. Blocked content is rejected. Review-triggering content escalates out
of low-ceremony flow instead of being silently accepted as instant context.

## Configuration

| Variable | Purpose |
|----------|---------|
| `AMBARA_KNOWLEDGE_REMOTE` | Git remote for the knowledge repo |
| `AMBARA_ACTIVE_REFS_ENABLED` | Enable instant active context sharing |
| `AMBARA_ACTIVE_REF_TTL_HOURS` | Maximum TTL for active context entries |
| `AMBARA_SOURCE_PROVIDER` | Source selector: `github`, `gitlab`, or `jira` |
| `AMBARA_SOURCE_REPOS` | Repos for GitHub PR or GitLab MR source inputs |
| `AMBARA_SOURCE_FIXTURE` | Local JSON fixture source for demos and no-network proof |
| `AMBARA_SIGNAL_PROVIDER` / `AMBARA_PR_SIGNAL_REPOS` | Legacy aliases for one release train |
| `AMBARA_GITLAB_BASE_URL` | Base URL for GitLab.com or self-hosted GitLab |
| `AMBARA_JIRA_BASE_URL` | Jira instance URL |
| `AMBARA_JIRA_PROJECTS` | Jira project keys |
| `AMBARA_CONTEXT_BUDGET_MODE` | `quiet`, `balanced`, or `deep` context budget |
| `AMBARA_VALUE_LEDGER_PATH` | Override the local aggregate JSONL value ledger path |
| `AMBARA_VALUE_LEDGER_ENABLED` | Set `false` to disable local aggregate value capture |
| `AMBARA_INPUT_PRICE_PER_MILLION` | Optional managed input-token price for currency estimates |
| `AMBARA_PRICE_CURRENCY` | Currency code for managed cost estimates |

Value receipts are enabled in startup/context packets. The persistent ledger is
local, aggregate-only, and on by default so Ambara can show conservative
token-savings ranges without end-user configuration. Currency estimates only
appear when a managed deployment supplies its own token price; otherwise Ambara
reports tokens.

## Troubleshooting

### The Agent Skips Context

Run:

```bash
ambara doctor --team --check-startup --strict
```

If the startup contract or MCP permissions are missing, repair project config:

```bash
ambara doctor --fix-project-config --team
```

Restart the MCP client after changing project configuration.

### `sync()` Or `context()` Is Unavailable

Check the knowledge remote and local cache:

```bash
ambara doctor --team --check-startup
ambara status
```

If the knowledge repo moved, regenerate project config with the new remote. If
the cache is corrupted, remove the local Ambara cache for that remote and run
`ambara doctor --team --check-startup` again.

### Active Handoffs Do Not Appear

Active context is disabled by default. Enable it only when the repo policy
allows short-lived handoffs:

```yaml
active_refs_enabled: true
active_ref_ttl_hours: 72
```

Then regenerate MCP config and verify:

```bash
ambara mcp-config --remote <knowledge-remote> --write-project
ambara doctor --team --check-startup
```

### Writes Are Blocked

Ambara evaluates writes before publishing. Credentials and secrets are blocked.
PII, confidentiality terms, and personnel content can require review. Remove the
sensitive content or route the entry through the reviewed path.

This same policy now applies to commit capture and CI capture, not
only interactive CLI or MCP writes.

### A Review Branch Was Created But No Review Request Appeared

Some write paths can save a review branch without opening a review request. When
that happens, Ambara now says so explicitly.

Treat that state as:

- a real saved artifact
- enough to inspect the diff or compare link
- not the same thing as a created review request

If review-request creation matters for your workflow, verify the forge-specific
auth and remote support for the write path you are using.

### Review Or Jira Source Inputs Do Not Appear

Only configured, labeled sources enter the source-input path.

For GitHub:

```bash
AMBARA_SOURCE_REPOS=your-org/repo1,your-org/repo2
```

For GitLab:

```bash
AMBARA_SOURCE_PROVIDER=gitlab
AMBARA_SOURCE_REPOS=your-group/repo1,your-group/repo2
AMBARA_GITLAB_BASE_URL=https://gitlab.example.com
GL_TOKEN=your-token
```

For Jira:

```bash
AMBARA_SOURCE_PROVIDER=jira
AMBARA_JIRA_BASE_URL=https://jira.example.com
AMBARA_JIRA_PROJECTS=PROJ1,PROJ2
JIRA_API_TOKEN=your-token
```

Unlabeled reviews and issues are ignored by design.

### Value Receipts Look Wrong

Ambara value accounting reports app-payload estimates only. It does not know
the client's full session, cache, or model bill unless a client provides that
data separately. Use:

```bash
ambara value --explain
```

to see the estimator, baseline, and privacy boundary. Negative net savings are
allowed and should be treated as a signal that the context packet was not worth
its cost for that turn.

If context is too noisy, use a quieter budget or local feedback:

```bash
AMBARA_CONTEXT_BUDGET_MODE=quiet
ambara feedback <entry-id> not-useful
ambara feedback <entry-id> pin
```
