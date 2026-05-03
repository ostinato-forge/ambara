# Jurati DX Design Spec — Ambient Capture & Seamless Onboarding

**Date:** 2026-05-03
**Status:** Draft (stress-tested, 2 review rounds, 30 findings resolved)
**Author:** Edgar Parenti
**Companion to:** `2026-05-02-jurati-design.md` (V1 core spec)

## Problem

Jurati V1 requires developers to make explicit MCP tool calls (`record`,
`propose`, `expire`) to share knowledge. This creates friction: developers must
context-switch from their work to think about knowledge management. The result
is low adoption — the tool exists but nobody uses it because writing to it feels
like a separate task.

## Goal

Knowledge capture should be a natural byproduct of development, not a separate
workflow. Developers write a commit message with a `jurati:` prefix, and the
system handles extraction, classification, branch creation, PR opening, and
merging. Reading knowledge back should require zero per-session setup — agents
surface relevant context automatically.

## Target

Tech companies using Claude Code (or similar agentic coding tools) for
development. Teams of 3 to 200+ developers across 1 to 50+ repos sharing a
single knowledge repository. The system must deliver value at every adoption
stage — from a solo developer to an org-wide deployment.

## Relationship to V1 Spec

This spec extends the V1 core spec. Where both address the same topic, the
rules below apply:

- **MCP tools:** This spec adds new tools (`context`, `search`) alongside the
  V1 tools (`query`, `read`, `list`, `record`, `propose`, `expire`, `validate`,
  `sync`). V1 tools are not renamed or removed.
- **Schema:** This spec adds an optional `source` field to frontmatter. The
  field is additive and backward-compatible with `schema_version: 1`.
- **Escalation model:** This spec does not change escalation levels or
  write-path rules. The tag-to-type mapping (Section 1.2) produces the same
  type/level combinations the V1 spec defines.
- **Privacy:** All V1 privacy constraints remain in force. This spec adds
  capture-specific constraints (Section 7).

---

## 1. The Write Path — Git-Conventional Capture

### 1.1 Convention

Developers signal knowledge capture by prefixing a commit message with
`jurati:`:

```
jurati: postgres connections pool at 20 max, not 50 — OOM on staging
```

Optional power-user tags refine the entry type. Tags are never required:

```
jurati(decision): switching from REST to gRPC for inter-service calls
jurati(principle): all inter-service calls go through the gateway
jurati(workflow): PRs require two approvals for database migrations
```

The commit body becomes the entry body. If no body is provided, the title
stands alone. The `jurati:` or `jurati(tag):` prefix is stripped from the
entry title — only the text after the colon becomes the title.

**Active entries do not use commit conventions.** Broadcasting ephemeral state
("I'm working on X") should not pollute git history. Active entries are created
via the existing `record(type="active")` MCP tool or `jurati active "message"`
CLI command. See Section 1.7.

### 1.2 Tag-to-Type Mapping

| Prefix | Entry type | Level | Merge behavior |
|--------|-----------|-------|----------------|
| `jurati:` (no tag) | project | L1 | Auto-merge after validation (see 1.8) |
| `jurati(decision):` | decision | L2 | Requires human review before merge |
| `jurati(principle):` | principle | L3 | Requires human review before merge |
| `jurati(workflow):` | workflow | L2 | Requires human review before merge |

Default (no tag) is `project` at L1. This means ~80% of captures auto-merge
with no human review required, keeping the knowledge repo current without
bottlenecks.

### 1.3 Extraction Pipeline

Both trigger paths (hook and Action) run the same extraction logic, which
routes through the existing `core/changes.py` pipeline (including
`_yaml_quote()` for title sanitization and `_render_entry()` for frontmatter
generation). No separate renderer exists.

The capture pipeline calls `core/changes.py` functions (`plan_record` for L1,
`plan_propose` for L2/L3) directly — it does NOT go through MCP tool handlers.
This is a batch write path that operates outside the MCP server process (in a
hook or Action). It uses the same core logic and git adapters but bypasses the
MCP tool boundary. The V1 MCP tools (`record`, `propose`) remain the
interactive write path for agent-mediated writes.

1. **Detect:** Scan commit message for `^jurati(\([a-z]+\))?:\s*(.+)$`.
   The `.+` requires at least one character after the colon — a bare `jurati:`
   with no title text is ignored. The hook prints a warning:
   `[jurati] skipped: empty title after "jurati:"` so the developer knows.
2. **Parse:** Extract optional tag and title from the first line. Strip the
   `jurati:` or `jurati(tag):` prefix — group 2 of the regex is the title.
3. **Body:** Remainder of the commit message (after the first line) becomes
   the entry body
4. **Safety check:** Scan title and body for common secret patterns (API keys,
   tokens, passwords, connection strings). Default patterns are hardcoded in
   `capture.py`; orgs can extend them via `secret_patterns` in
   `.jurati/config.yaml` on the knowledge repo. If a match is found, escalate
   to L2 (requires human review) regardless of tag, and add a
   `[possible-secret]` label to the PR. To dismiss a false positive, a
   reviewer with write access to the knowledge repo removes the label, which
   unblocks auto-merge.
5. **Derive ID:** `{repo-slug}-{slugified-title}` truncated to 120 chars.
   If collision exists, append `-{short-hash}` (first 6 chars of
   `sha256(repo:commit-sha:message)`)
6. **Render:** Generate the full entry markdown with YAML frontmatter using
   `core/changes.py`. Title passes through `_yaml_quote()`.
7. **Write:** Create branch on `jurati-knowledge`, commit, push. Branch name
   is `jurati/{repo-slug}/{entry-id-suffix}` to avoid cross-repo collisions.

### 1.4 Deduplication

Deduplication uses two checks:

1. **Entry file on `main`:** Before creating a branch, check whether the
   derived entry file path already exists on `main` via `git ls-tree`. If it
   does, the entry was already captured and merged — skip. If `main` does not
   exist yet (empty/new knowledge repo), this check passes (no collision).
2. **Branch existence:** If the entry file is not on `main`, check whether the
   branch `jurati/{repo-slug}/{entry-id-suffix}` exists remotely. If it does,
   a capture is already in progress — skip.

This two-layer check is robust against branch lifecycle: merged branches are
detected by the file check, in-flight branches by the ref check. If both the
git hook and GitHub Action fire for the same commit, the second write is a
no-op.

**Cross-repo title collision:** Two repos committing `jurati: fix auth timeout`
produce entry IDs `api-service-fix-auth-timeout` and
`frontend-fix-auth-timeout` — different IDs because the repo slug is always
the first segment. Entries with identical titles from the same repo get the
`-{short-hash}` suffix.

### 1.5 PR Batching

When a single push contains multiple `jurati:` commits, the GitHub Action
batches them into a single PR to avoid PR flood. The PR title summarizes the
batch: `jurati: 3 entries from api-service`. Each entry is a separate file
change within the PR. The batch branch name is
`jurati/{repo-slug}/batch-{push-sha-prefix}`.

Before creating a batch PR, the Action checks for an existing open PR with the
same branch name prefix. If one exists, force-push to that branch instead of
creating a new PR.

The git hook processes commits individually since pushes are typically single
commits.

### 1.6 Source Attribution

Every captured entry includes git provenance in the frontmatter as an optional
`source` field (additive to V1 schema, `schema_version: 1` compatible):

```yaml
source:
  repo: api-service
  commit: abc123def
  author: maria@company.com
```

`source.author` is from `git config user.email` and is informational, not an
identity assertion. It is equivalent to standard git commit authorship — it
can be spoofed. Orgs requiring authenticated attribution should enforce signed
commits in their GitHub Action workflow.

The `source` field is optional in the schema. Entries created via MCP tools
(without the capture pipeline) do not include it.

### 1.7 Active Entries — No Commit Required

Active entries (L0) are ephemeral presence signals. They must NOT require a git
commit in the source repo, because:

- Empty commits pollute `git log` and `git blame`
- Ephemeral state should not create permanent history
- Active entries already have a working path via MCP `record(type="active")`

Active entries are created through:

- **CLI:** `jurati active "working on auth refactor" --expires 2h`
- **MCP tool:** `record(type="active", ...)` (existing V1 tool)
- **Agent-mediated:** Developer tells their agent "let the team know I'm
  working on auth" and the agent calls `record`

All three paths push to the active ref (`jurati/active/<client>/<entry-id>`)
as defined in the V1 spec. No PR, no branch, no source-repo commit.

### 1.8 Auto-Merge Behavior for L1

"Auto-merge" for L1 entries means: the GitHub Action (or a bot on the knowledge
repo) merges the PR automatically after the following checks pass:

1. **Schema validation:** `jurati validate` passes on the entry
2. **Secret scan:** No `[possible-secret]` label (Section 1.3 step 4)
3. **Contradiction check:** No `[possible-contradiction]` label (Section 4.3)

If any check fails, the PR stays open for human review.

**Required infrastructure:** The GitHub Action needs a token with `contents:
write` permission on the knowledge repo. This can be:
- A fine-grained PAT stored as `JURATI_KNOWLEDGE_TOKEN` in repo secrets
- A GitHub App installation token (preferred for org-wide)
- The built-in `GITHUB_TOKEN` if the Action runs within the knowledge repo

The knowledge repo must have branch protection on `main` with the bot/token
added to the bypass list, or with "allow auto-merge" enabled. `jurati doctor`
checks this configuration.

### 1.9 Merge Strategy Compatibility

The GitHub Action must handle all common merge strategies:

| Strategy | Behavior |
|----------|----------|
| **Merge commit** | Scans all commits in the push |
| **Squash merge** | Scans the squash commit message AND the PR body for `jurati:` lines |
| **Rebase merge** | Scans all commits; dedup keys on `message-hash` (not `commit-sha`) to handle SHA changes |

For squash merges where the original `jurati:` commit messages were collapsed:
if the PR body or squash message contains `jurati:` lines, each line is
captured as a separate entry.

---

## 2. Trigger Mechanisms

### 2.1 GitHub Action (org-wide, zero local setup)

A reusable GitHub Action that runs on `push` events to configured branches,
scans new commits for the `jurati:` prefix, and runs the extraction pipeline.

**The Action triggers only on pushes to specific branches** (default: the
repo's default branch). It does NOT trigger on:
- Feature branches (to prevent orphan entries from abandoned work)
- Fork PRs (to prevent injection from untrusted contributors)
- `pull_request` events

Developers who want to capture knowledge from feature-branch work use the git
hook (Section 2.2), which is an intentional local action.

**Adoption tiers:**

| Tier | Setup | Who it's for |
|------|-------|-------------|
| **Single repo** | Copy `.github/workflows/jurati.yml` into one repo | Individual team trying it out |
| **Org-wide opt-in** | Reusable workflow, repos opt in via a one-liner workflow file | Org with a standard but not a mandate |
| **Org default** | Org-level required workflow or repo template | Org that's all-in |

**Single-repo workflow file:**

```yaml
name: jurati-capture
on:
  push:
    branches: [main]
concurrency:
  group: jurati-capture-${{ github.repository }}
  cancel-in-progress: false
jobs:
  capture:
    uses: jurati/capture-action@v1
    with:
      knowledge_remote: ${{ secrets.JURATI_KNOWLEDGE_REMOTE }}
      knowledge_token: ${{ secrets.JURATI_KNOWLEDGE_TOKEN }}
```

The `concurrency` group serializes Action runs per source repo to prevent
duplicate PRs from rapid pushes.

**Opt-in one-liner (when org provides the reusable workflow):**

```yaml
name: jurati-capture
on:
  push:
    branches: [main]
jobs:
  capture:
    uses: ./.github/workflows/jurati-capture.yml
```

### 2.2 Git Hook (immediate, local feedback)

A `post-commit` hook installed via `jurati install-hook`. Scans the most recent
commit for `jurati:` prefix and runs the extraction pipeline immediately.

```bash
jurati install-hook        # Installs post-commit hook in current repo
jurati install-hook --global  # Installs as a global git hook template
```

Developer sees immediate feedback:

```
[jurati] captured: "postgres connections pool at 20 max" → PR #47
```

**Offline handling:** If the push to the knowledge remote fails (network error,
auth failure), the hook:

1. Writes a pending-capture marker to `.git/jurati-pending/<commit-sha>.json`
2. Prints: `[jurati] offline — queued for next push`
3. On the next successful `jurati:` capture (or via `jurati flush`), retries
   all pending captures

The `jurati flush` command retries all pending captures in `.git/jurati-pending/`.
The `pre-push` hook (optionally installed alongside `post-commit`) also triggers
a flush automatically.

**Limitation:** The pending queue lives in `.git/jurati-pending/` and is
local to the clone. If the developer switches machines or re-clones, pending
captures are lost. This is acceptable: the commits themselves are in git
history, and the GitHub Action (running on `main`) serves as the backstop
capture mechanism for any commits the hook missed.

**Push retry on conflict:** If `git push` to the knowledge repo fails with a
non-fast-forward error (concurrent push from another developer/Action), the hook
retries with exponential backoff (up to 3 attempts, jittered delays). This
handles the common case of 2-3 developers pushing simultaneously.

### 2.3 Both Paths Coexist

A team can run both the GitHub Action and git hooks simultaneously. The
deduplication mechanism (Section 1.4) prevents double-writes. This allows:

- Developers who prefer local feedback use the hook
- Developers who prefer zero-setup get coverage from the Action
- The hook captures from feature branches; the Action captures from main

---

## 3. The Read Path — Zero-Config Context Delivery

### 3.1 Session Start

When a developer starts a Claude Code session in a repo with Jurati configured,
the agent calls `context` (a new MCP tool) and receives a structured summary:

```
Active now (3 entries):
- @maria is refactoring the auth middleware (expires in 45min)
- @chen is load-testing the /orders endpoint (expires in 2hr)
- staging deploy is frozen until 3pm PT — infra team

Recent decisions (2 this week):
- postgres pool capped at 20 connections (was 50, caused OOM)
- switching /users cache from 5min to 30s after stale-data complaints

Relevant to this repo (api-service):
- gRPC migration for inter-service calls — approved, in progress
- new rate-limit headers required on all public endpoints
```

### 3.2 Query Intelligence — The Trust Layer

Natural language queries are Jurati's primary interface for agents. This is
the trust surface — if queries return irrelevant results or miss critical
entries, developers stop trusting the system and stop writing `jurati:` commits.

**Design principle:** Better to return 3 highly relevant entries than 12
sort-of-relevant ones. Precision over recall. When in doubt, surface less —
but never miss something critical.

**Query pipeline (4 stages):**

```
"what's the team doing about caching?"
        |
        v
+---------------------+
| 1. PARSE INTENT     |  Extract: topic, scope, timeframe, type filter
+---------------------+
        |
        v
+---------------------+
| 2. CANDIDATE POOL   |  Active entries (always), keyword/tag matches,
|                     |  repo-linked entries, recency window
+---------------------+
        |
        v
+---------------------+
| 3. RANK & SCORE     |  Keyword overlap, tag match, recency decay,
|                     |  type weight, repo proximity
+---------------------+
        |
        v
+---------------------+
| 4. THRESHOLD CUT    |  Hard minimum relevance score.
|                     |  Top N above threshold. Honest zeros.
+---------------------+
```

**Scoring dimensions:**

- **Keyword overlap:** BM25-style scoring on title + body + tags, using an
  in-memory inverted index built during `load_index_from_repo`. The index maps
  terms to posting lists with term frequencies. BM25 over 1500 short documents
  is trivially fast in Python.
- **Tag match:** Exact tag matches weighted heavily
- **Recency:** Exponential decay — entries from this week score much higher
  than entries from 3 months ago
- **Type weight:** principles > decisions > workflows > projects for ranking
  (not filtering)
- **Repo proximity:** Entries from the current repo or its configured
  dependencies rank higher (see Section 3.5)

BM25 produces the term-relevance score. Recency, type, and repo proximity are
separate ranking signals combined as weighted factors. These are distinct
concerns and must not be conflated in the implementation.

**Critical behaviors:**

1. **Honest zeros.** If nothing matches, return "No entries found." Never pad
   with loosely-related results.
2. **Deterministic scoring.** Every returned entry has a numeric relevance
   score. Rankings are explainable and reproducible.
3. **Active bypass.** Active entries (L0) always surface regardless of query —
   they are safety signals, not search results.
4. **Repo graph awareness.** Config in the knowledge repo maps repo
   dependencies. Entries from dependency repos rank higher than unrelated repos.
5. **Exact match escalation.** If the query contains an exact entry ID or title
   substring, that entry goes to the top regardless of score.

**Contradiction detection is best-effort.** Keyword-based overlap will miss
semantic paraphrases ("postgres pool max 30" vs "pg connection limit thirty").
This is a known limitation. L2/L3 entries require human review, which is the
real defense against conflicting authoritative content.

**Index rebuild optimization:** The inverted index is rebuilt from repo contents
after sync. To avoid unnecessary rebuilds on the 300-second sync interval: hash
the tree object of `main` after fetch. If unchanged since last rebuild, skip.

**Testing the trust layer:**

- Golden-set tests: 50+ curated query-to-expected-results pairs
- Precision tests: for specific queries, specific entries must NOT appear
- Regression suite: every reported bad result becomes a permanent test case
- The golden set starts small and grows with real usage

### 3.3 MCP Tool Interface

New tools added by this spec (V1 tools remain unchanged):

```
context(repo?, scope?)
  → Active entries + recent decisions + repo-linked items
  → Called automatically at session start
  → Complements V1 `list` (which returns raw entry lists)

search(query, tags?, type?, project?, status?, max_results?, include_expired?)
  → Ranked entries above threshold, with scores
  → Superset of V1 `query` with BM25 scoring
  → V1 `query` remains available for backward compatibility
```

V1 tools `read`, `list`, `record`, `propose`, `expire`, `validate`, and `sync`
are unchanged.

### 3.4 Human Access (Non-Agent Users)

Not everyone uses an agent. Knowledge must be accessible without one:

- **`jurati search <query>`** — CLI search across the knowledge repo
- **GitHub browse** — the knowledge repo is readable markdown on github.com
- **PR notifications** — developers subscribed to the knowledge repo see
  L2/L3 entries as PRs to review

### 3.5 Repo-Graph Config

The knowledge repo's `.jurati/config.yaml` includes an optional `repo_graph`
section that maps repo dependencies:

```yaml
repo_graph:
  api-service:
    depends_on: [shared-libs, auth-service]
  frontend:
    depends_on: [shared-libs, api-service]
  shared-libs:
    depends_on: []
```

When `context` or `search` is called with `repo="api-service"`, entries from
`shared-libs` and `auth-service` rank higher than entries from `frontend` or
`marketing-site`. If no `repo_graph` is configured, repo proximity scoring
is disabled — all repos rank equally.

---

## 4. The Curation Cycle — How Knowledge Stays Healthy

### 4.1 Automatic Expiry

Active entries (L0) have `expires_at`. The MCP server stops surfacing them
after expiry. No human action required.

### 4.2 Staleness Detection (Weekly Automated PR)

A scheduled GitHub Action (or cron in the MCP server) scans weekly:

- Entries older than 90 days with no `updated_at` changes
- Before creating a PR, checks for an existing open PR with the title prefix
  `jurati: weekly hygiene`. If one exists, update its body and force-push the
  branch instead of creating a new PR.
- PR body lists each stale entry with options: archive, confirm still valid,
  or mark for update
- One reviewer handles it — 5 minutes per week, not a dedicated role

### 4.3 Contradiction Detection (On Write)

When a new entry arrives, the pipeline checks for conflicts using title and
keyword overlap against existing entries in the same type directory:

```
New entry: "postgres pool capped at 30 connections"
Existing:  "postgres pool capped at 20 connections" (2 weeks ago)

→ PR label: [possible-contradiction]
→ PR comment: "This may contradict decisions/postgres-pool-limit.md
   — does this supersede it?"
```

If the `[possible-contradiction]` label is present, auto-merge is blocked
(Section 1.8 step 3). The author resolves by adding `supersedes:
postgres-pool-limit`, editing to clarify, or removing the label after review.

When entry B supersedes entry A, entry A receives `superseded_by: B`
automatically and stops appearing in search results.

### 4.4 Curation Rhythm

| Frequency | What happens | Who acts |
|-----------|-------------|----------|
| Continuous | Active entries auto-expire | Nobody |
| On each write | Contradiction check flags conflicts | Entry author |
| Weekly | Staleness PR for 90-day-old entries | PR reviewer (rotating) |
| Quarterly | Principles review — are L3 entries still true? | Tech leads, 30min |

### 4.5 Growth Projections

| Time | Total entries | Active (visible) | Archived |
|------|--------------|-------------------|----------|
| Month 1 | ~50 | ~45 | ~5 |
| Month 6 | ~400 | ~200 | ~200 |
| Year 1 | ~800 | ~300 | ~500 |
| Year 2 | ~1,500 | ~400 | ~1,100 |

The active set plateaus because entries expire or get superseded. The repo
grows but what agents see stays manageable through the filtering pipeline.

**Branch hygiene:** The GitHub Action aggressively deletes branches after PR
merge. The MCP server uses `git fetch --prune` during sync to clean up stale
remote refs. This prevents ref accumulation from degrading fetch performance.

---

## 5. The Onboarding Ladder — Zero to Org-Wide

### 5.1 Layer 1: CLAUDE.md Discovery (Recommended Default)

The primary zero-setup path. Team repos include a block in `CLAUDE.md`:

```
## Shared Knowledge

This project uses Jurati for shared team knowledge.
Knowledge repo: git@github.com:acme/jurati-knowledge.git

If Jurati is not yet configured, run: jurati doctor
```

When a developer opens Claude Code in this repo:
- If Jurati MCP is already configured: the agent uses it normally
- If not configured but jurati is installed: the agent sees the CLAUDE.md
  instruction and offers to run `jurati doctor` to configure. One confirmation.
- If jurati is not installed: the agent mentions it on first session. The
  developer can install it when they're ready. No error, no broken state.

This approach is safe for mixed-adoption teams: developers who haven't
installed jurati see a mention in CLAUDE.md but experience no errors. Developers
who have installed it get auto-discovery.

### 5.2 Layer 2: Repo Ships MCP Config (Confirmed Teams)

For teams where every developer has jurati installed (confirmed adoption),
repos can include `.claude/settings.json` with direct MCP config:

```json
{
  "mcpServers": {
    "jurati": {
      "command": "jurati",
      "args": ["serve"],
      "env": {
        "JURATI_KNOWLEDGE_REMOTE": "git@github.com:acme/jurati-knowledge.git"
      }
    }
  }
}
```

**Only use this when the team has confirmed jurati is installed for all
members.** If jurati is not on a developer's PATH, Claude Code will show an
MCP connection error every session. This is the right choice for org-wide
deployments (Stage 5) where jurati is part of the standard developer setup,
not for early adoption.

### 5.3 Layer 3: `jurati doctor` Cold Start

Developer heard about Jurati, has it installed, but their repo has nothing:

```bash
jurati doctor
```

Doctor detects: installed but no remote configured. Discovery steps:
1. Check `.claude/settings.json` for existing MCP config
2. Check `CLAUDE.md` for a knowledge repo URL
3. Check for a `.jurati-remote` file in the repo root
4. If none found, ask the developer for the URL

Doctor also checks for consistency:
- If both hook and Action are configured, verify they point to the same
  knowledge repo URL. Warn on mismatch.
- If branch protection is missing on the knowledge repo's `main`, warn.
- If the write token lacks merge permissions, warn.

Then writes the MCP config. Next session, it's live.

### 5.4 Layer 4: Full Bootstrap

Brand-new user, from scratch:

```bash
pip install jurati
jurati quickstart ~/jurati-knowledge
# (push the knowledge repo to a remote)
jurati mcp-config --remote <git-url>
# (paste into Claude Code settings)
```

Three commands, two minutes. This is only for the first person on a team.

### 5.5 Adoption Stages

| Stage | Who | What they do | Value they get |
|-------|-----|-------------|----------------|
| Solo | 1 developer | Install, quickstart | Agent remembers across sessions |
| Pair | 2-3 developers | Share knowledge repo URL | Stop re-explaining decisions to each other |
| Team | 5-15 developers | Add GitHub Action to repo | New members onboard via agent context |
| Multi-team | 20-50 developers | Multiple teams, same knowledge repo | Cross-team visibility without meetings |
| Org-wide | 50-200+ | Org-level workflow, repo templates | Standard async knowledge practice |

Each stage delivers value independently. No "it gets good once everyone's using
it."

### 5.6 What Drives Adoption

| Transition | Driver |
|-----------|--------|
| Solo → Pair | "My agent knew that" moment |
| Pair → Team | Team sees reduced re-explanation |
| Team → Multi-team | Other teams notice better-informed agents |
| Multi-team → Org | Admin convenience and consistency |

### 5.7 Failure Modes and Guardrails

**"Nobody writes jurati: commits"** — The hook/action shows a count in CI.
Not a metric to optimize — just visibility. Forcing adoption won't help.

**"Too much noise, agents surface irrelevant stuff"** — Query layer bug. Fix
relevance scoring. The golden-set test suite catches regressions.

**"Stale entries mislead agents"** — Weekly hygiene PR handles this. After
90 days without update, entries get lower relevance scores automatically.

**"One team's entries pollute another team's context"** — Repo-graph awareness
in the query layer prevents this. Entries from unrelated repos don't surface
unless explicitly searched.

**"Orphan entries from abandoned feature branches"** — The GitHub Action only
fires on pushes to `main` (or configured branches). Feature-branch captures
via git hook are intentional local actions by the developer.

**"jurati not installed but mentioned in CLAUDE.md"** — The agent sees the
mention but cannot configure MCP without the binary. It informs the developer
once. No error, no broken state. If `.claude/settings.json` has MCP config
but jurati is not installed, Claude Code will show an MCP connection error —
which is why Layer 1 (CLAUDE.md) is recommended over Layer 2 (settings.json)
for mixed-adoption teams.

---

## 6. Components To Build

### 6.1 New Modules

| Component | Location | Purpose |
|-----------|----------|---------|
| `capture.py` | `src/jurati/capture/` | Extraction pipeline: parse commit, derive ID, render entry, secret scan |
| `hooks.py` | `src/jurati/capture/` | Git hook implementation (post-commit, offline queue, flush) |
| `scoring.py` | `src/jurati/core/` | BM25 inverted index, multi-signal ranking, deterministic scoring |
| `curation.py` | `src/jurati/core/` | Staleness detection, contradiction detection logic |

### 6.2 GitHub Action

| Component | Location | Purpose |
|-----------|----------|---------|
| `action.yml` | `action/` | GitHub Action metadata, inputs, permissions |
| `entrypoint.sh` | `action/` | Action entrypoint — must never `eval` commit content |

### 6.3 CLI Extensions

| Command | Purpose |
|---------|---------|
| `jurati install-hook` | Install post-commit hook (and optionally pre-push flush) |
| `jurati install-hook --global` | Install as global git hook template |
| `jurati capture <commit-sha>` | Manually run capture on a specific commit |
| `jurati active "message" --expires 2h` | Create L0 active entry without committing |
| `jurati flush` | Retry all pending captures from `.git/jurati-pending/` |

### 6.4 Enhancements to Existing Modules

| Module | Enhancement |
|--------|-------------|
| `core/search.py` | Add BM25 inverted index, built during `load_index_from_repo` |
| `core/schema.py` | Add optional `source: SourceMeta \| None` to `Frontmatter` |
| `server.py` | Add `context` and `search` tools |
| `cli.py` | Add `install-hook`, `capture`, `active`, `flush` commands |
| `git/config.py` | Add `repo_graph` config for dependency awareness |
| `git/branch.py` | Add push retry with exponential backoff (3 attempts, jitter) |


---

## 7. Privacy Constraints

All constraints from the V1 spec remain in force. Additionally:

- The GitHub Action must not log commit message content beyond what GitHub
  already captures in workflow logs
- The git hook must not send any data to external services other than the
  configured `jurati-knowledge` remote
- Source attribution (repo, commit, author) is git provenance — it is
  informational, not an identity assertion. It must not be treated as
  authenticated identity without commit signing.
- The `context` tool must not persist which entries were surfaced or which
  queries were made
- Commit message content is data, never code. No pipeline stage may execute
  or evaluate message content (no `eval`, `sh -c`, or unquoted variable
  expansion in hook scripts or Action entrypoints)

---

## 8. Deployment Prerequisites

Before the capture pipeline can operate, the knowledge repo must have:

1. **Branch protection on `main`** — no direct pushes. The capture pipeline
   always creates branches, never pushes to `main`. This is the primary
   defense against malicious or incorrect L1 content reaching the source of
   truth without validation.
2. **A write token** — a fine-grained PAT or GitHub App installation token
   scoped to `contents:write` on the knowledge repo. For org-wide deployment,
   a GitHub App is preferred.
3. **Auto-merge enabled** (for L1) — with the bot/token in the branch
   protection bypass list, or with GitHub's "allow auto-merge" feature.

`jurati doctor` checks all three and reports what's missing.

---

## 9. Testing Strategy

### Capture Pipeline Tests

- Commit message parsing: `jurati:`, `jurati(decision):`, edge cases
- Title stripping: `jurati: foo` → title is `foo`, not `jurati: foo`
- Secret pattern detection: API keys, tokens flagged; normal text passes
- ID generation: deterministic, collision-resistant, valid slug format
- Body extraction: single-line commits, multi-line with body
- Deduplication: same commit processed twice is a no-op (both checks)
- YAML injection: titles with `:`, `#`, `{}`, newlines sanitized via
  `_yaml_quote()`

### Merge Strategy Tests

- Merge commit: all commits scanned
- Squash merge: PR body scanned for `jurati:` lines
- Rebase merge: dedup keys on message-hash, not commit-sha

### Query Trust Tests (Golden Set)

- Start with 50+ curated query-to-results pairs
- Precision tests: specific entries must NOT appear for specific queries
- Regression tests: every bad result reported in production becomes a test
- Scoring stability: same query + same index = same ranking, always

### Hook/Action Integration Tests

- Hook installs cleanly, runs on commit, captures correctly
- Hook queues pending captures when offline, flushes on reconnect
- Hook retries on push conflict (3 attempts with backoff)
- Action processes multi-commit pushes, batches PRs
- Action concurrency group prevents duplicate PRs
- Action only fires on configured branches, not feature branches or forks
- Both paths coexist without duplicating entries

### Curation Tests

- Staleness detection fires at 90 days, not before
- Contradiction detection: overlapping titles flagged, non-overlapping not
- Contradiction label blocks auto-merge
- Supersession chain: B supersedes A, A stops appearing in search
- Weekly hygiene updates existing open PR instead of creating a new one

### Onboarding Tests

- CLAUDE.md with knowledge repo URL enables agent-driven setup
- `.claude/settings.json` with MCP config works when jurati is installed
- `.claude/settings.json` without jurati installed shows MCP error (expected)
- `jurati doctor` discovers URL from CLAUDE.md, .jurati-remote, or settings
- `jurati doctor` warns on hook/Action URL mismatch
- `jurati install-hook` creates a working post-commit hook
- Hook and Action both point at the same knowledge repo

---

## 10. Non-Goals

- No AI-powered commit message rewriting or suggestion
- No automatic classification beyond tag parsing — the developer's tag
  (or lack thereof) is authoritative
- No commit message enforcement or rejection — `jurati:` is opt-in
- No dashboard, analytics, or participation metrics
- No cross-org knowledge federation
- No modification of the developer's git workflow beyond the optional hook
- No capture from fork PRs or untrusted contributors
